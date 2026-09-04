# ==========================================
# 探针：验证 realtime function calling 的完整闭环
# 1) 模型先说话/调工具（工具内容不发音）
# 2) 后端回传工具结果 + response.create
# 3) 模型是否自动继续输出语音（audio delta）
# 用法：PYTHONPATH=. python tests/probe_tools.py
# ==========================================
import asyncio
import json

import websockets

from app.config import DASHSCOPE_WS_URL, build_ssl_context, get_api_key

TOOL = {
    "type": "function",
    "function": {
        "name": "write_to_board",
        "description": "把内容写到黑板上。当用户要求写黑板/板书时调用。",
        "parameters": {
            "type": "object",
            "properties": {"content": {"type": "string", "description": "黑板内容"}},
            "required": ["content"],
        },
    },
}


# ==========================================
# base64 音频块换算秒数（24kHz 16bit 单声道）
# ==========================================
def b64_seconds(b64: str) -> float:
    """
    把 base64 PCM 换算成秒数。
    Args:
        b64: base64 字符串 (str)
    Returns:
        float: 秒数
    """
    pad = 2 if b64.endswith("==") else (1 if b64.endswith("=") else 0)
    return max(0.0, (len(b64) * 3 // 4 - pad) / 48000)


# ==========================================
# 读取一个 response 周期，统计音频/字幕/工具调用
# ==========================================
async def read_response(ws) -> dict:
    """
    读到 response.done 为止，汇总本周期的音频秒数、字幕、工具调用。
    Args:
        ws: WebSocket 连接
    Returns:
        dict: {audio_sec, text, tool_call:{call_id,name,arguments}|None}
    """
    audio_sec = 0.0
    text = ""
    tool_call = None
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=30)
        ev = json.loads(raw)
        etype = ev.get("type", "")
        if etype == "response.audio.delta":
            audio_sec += b64_seconds(ev.get("delta", ""))
        elif etype in ("response.audio_transcript.delta", "response.text.delta"):
            text += ev.get("delta", "")
        elif etype == "response.function_call_arguments.done":
            tool_call = {
                "call_id": ev.get("call_id", ""),
                "name": ev.get("name", ""),
                "arguments": ev.get("arguments", ""),
            }
        elif etype == "error":
            print("  ERROR:", json.dumps(ev, ensure_ascii=False)[:400])
        elif etype == "response.done":
            break
    return {"audio_sec": round(audio_sec, 2), "text": text, "tool_call": tool_call}


# ==========================================
# 主流程：两轮 response 验证"说话→工具→继续说话"
# ==========================================
async def main() -> None:
    """
    第一轮期望：口头讲解 + 工具调用；回传结果后第二轮期望：继续语音。
    """
    headers = {"Authorization": f"Bearer {get_api_key()}"}
    async with websockets.connect(
        DASHSCOPE_WS_URL, additional_headers=headers, ssl=build_ssl_context()
    ) as ws:
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": (
                    "你是法语老师。用户要求写黑板时，先口头讲一句，"
                    "再调用 write_to_board 工具；工具返回后继续口头总结。"
                ),
                "tools": [TOOL],
            },
        }))
        await ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "请把勾股定理写到黑板上"}],
            },
        }))
        await ws.send(json.dumps({"type": "response.create"}))

        print("== 第一轮 response ==")
        r1 = await read_response(ws)
        print("  口头字幕:", r1["text"])
        print("  语音时长:", r1["audio_sec"], "秒")
        if not r1["tool_call"]:
            print("  未触发工具调用，探针结束")
            return
        print("  工具调用:", r1["tool_call"]["name"], r1["tool_call"]["arguments"][:80])

        # 回传工具结果，触发第二轮
        await ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": r1["tool_call"]["call_id"],
                "output": json.dumps({"status": "ok", "message": "已写到黑板"}),
            },
        }))
        await ws.send(json.dumps({"type": "response.create"}))

        print("== 第二轮 response（工具后是否继续说话）==")
        r2 = await read_response(ws)
        print("  口头字幕:", r2["text"])
        print("  语音时长:", r2["audio_sec"], "秒")
        print("结论:", "工具后继续输出语音 ✅" if r2["audio_sec"] > 0 else "工具后没有语音 ❌")


if __name__ == "__main__":
    asyncio.run(main())
