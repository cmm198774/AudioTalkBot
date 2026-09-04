# ==========================================
# DashScope Realtime WebSocket 桥接：管理一个实时对话连接
# 上行：浏览器音频 → input_audio_buffer.append
# 下行：服务端事件分流 → 音频/字幕/黑板/打断/状态/错误
#
# 板书通过 write_to_board 工具调用实现：模型口头讲解与工具调用
# 交替进行，工具参数（黑板内容）是结构化文本、不被 TTS 朗读，
# 天然"只写不读"，无需对音频流做任何掐断。
# 工具结果回传后发 response.create 让模型继续口头总结，
# 一轮用户发言内可多次"说话→写黑板→说话"。
# ==========================================
import asyncio
import json
import logging

from websockets.asyncio.client import connect as ws_connect

from app.config import (
    BOARD_TOOL,
    DASHSCOPE_WS_URL,
    OUTPUT_MODE_MODALITIES,
    build_ssl_context,
    get_api_key,
)
from app.protocol import (
    build_audio_append,
    build_history_events,
    build_response_create,
    build_session_update,
    build_tool_output,
)

logger = logging.getLogger(__name__)

# 板书工具名：只有它的调用内容会上黑板
_BOARD_TOOL_NAME = BOARD_TOOL["function"]["name"]

# 工具结果统一回传"已写入"，模型据此继续口头总结
_TOOL_OK_OUTPUT = json.dumps({"status": "ok", "message": "已写到黑板"}, ensure_ascii=False)

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
    "response.function_call_arguments.delta",
)


# ==========================================
# 实时对话桥接器
# ==========================================
class RealtimeBridge:
    """
    管理一条 DashScope Realtime 连接，把服务端事件翻译成前端消息。
    前端消息格式：
        audio / interrupt / transcript / board / state / error / new_response
    """

    def __init__(self, send_to_client, on_final_transcript=None, api_key: str = "",
                 ws_factory=None):
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
        self._speaking = False
        self._need_new_bubble = True  # 标记是否需要创建新字幕气泡
        self._assistant_text = ""     # 本轮用户发言对应的口头文本，持久化用
        self._pending_calls = []      # 当前 response 内待回传结果的工具调用 ID
        self._interrupted = False     # 当前 response 是否被用户打断

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
        return await ws_connect(url, additional_headers=headers, ssl=build_ssl_context())

    # ==========================================
    # 建立连接并配置会话
    # ==========================================
    async def connect(self, instructions: str, output_mode: str, history=None) -> None:
        """
        连接 DashScope，发送 session.update（含板书工具），可选注入历史，
        然后启动接收循环。
        Args:
            instructions: system prompt (str)
            output_mode: audio / text / audio_text (str)
            history: 历史对话记录列表，用于恢复上下文 (list)
        """
        modalities = OUTPUT_MODE_MODALITIES.get(output_mode, ["text", "audio"])
        headers = {"Authorization": f"Bearer {self._api_key}"}
        self._ws = await self._ws_factory(DASHSCOPE_WS_URL, headers)
        await self._send_event(build_session_update(instructions, modalities, tools=[BOARD_TOOL]))
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
        await self._send_event(build_session_update(instructions, modalities, tools=[BOARD_TOOL]))

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
            self._need_new_bubble = True  # 用户开口，标记需要新气泡
            self._interrupted = True      # 进行中的回复被打断，不再续说
            await self._emit({"type": "interrupt"})
            await self._emit({"type": "state", "value": "listening"})
        elif etype == "response.created":
            self._pending_calls = []
            self._interrupted = False
            if self._need_new_bubble:
                await self._emit({"type": "new_response"})
                self._need_new_bubble = False
                self._assistant_text = ""  # 新一轮用户发言，口头文本重新累积
            await self._emit({"type": "state", "value": "thinking"})
        elif etype == "response.function_call_arguments.done":
            await self._handle_function_call(event)
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
    # 内部：回复音频增量（直接转发，不做掐断）
    # ==========================================
    async def _handle_audio_delta(self, event: dict) -> None:
        """
        转发音频增量。模型不会朗读板书内容（走工具参数），
        因此音频流全部都是该说的话，直接转发。
        Args:
            event: response.audio.delta 事件 (dict)
        """
        delta = event.get("delta", "")
        if not delta:
            return
        if not self._speaking:
            self._speaking = True
            await self._emit({"type": "state", "value": "speaking"})
        await self._emit({"type": "audio", "data": delta})

    # ==========================================
    # 内部：回复文本增量（口头字幕）
    # ==========================================
    async def _handle_transcript_delta(self, event: dict) -> None:
        """
        累积口头文本并转发字幕增量。
        Args:
            event: 字幕/文本增量事件 (dict)
        """
        delta = event.get("delta", "")
        if not delta:
            return
        self._assistant_text += delta
        await self._emit({"type": "transcript", "role": "assistant", "delta": delta, "final": False})

    # ==========================================
    # 内部：工具调用完成（板书上黑板）
    # ==========================================
    async def _handle_function_call(self, event: dict) -> None:
        """
        工具参数解析后上黑板（每次调用作为一个新黑板段），
        并记录 call_id 以便 response.done 时回传结果。
        Args:
            event: response.function_call_arguments.done 事件 (dict)
        """
        call_id = event.get("call_id", "")
        if not call_id:
            return
        self._pending_calls.append(call_id)
        if event.get("name", "") != _BOARD_TOOL_NAME:
            logger.warning("未知工具调用: %s", event.get("name"))
            return
        try:
            content = json.loads(event.get("arguments", "") or "{}").get("content", "")
        except json.JSONDecodeError:
            content = ""
        if content:
            await self._emit({"type": "board", "delta": content, "new_segment": True})

    # ==========================================
    # 内部：回复结束（工具编排 / 回合收尾）
    # ==========================================
    async def _handle_response_done(self) -> None:
        """
        本 response 含工具调用时：回传结果并触发模型继续口头总结
        （被打断则只回传不续说）；否则回合收尾，持久化口头文本。
        """
        self._speaking = False
        if self._pending_calls:
            calls = self._pending_calls
            self._pending_calls = []
            for call_id in calls:
                await self._send_event(build_tool_output(call_id, _TOOL_OK_OUTPUT))
            if not self._interrupted:
                await self._send_event(build_response_create())
                return  # 回合继续，不持久化、不切 listening
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
