# ==========================================
# 探针：验证不同 modalities 下 write_to_board 工具调用是否可用
# 场景 A：["audio"]（仅语音模式，用户报告工具不触发）
# 场景 B：["text", "audio"]（语音+文字模式，此前已验证可用）
# 用法：PYTHONPATH=. python tests/probe_board_modes.py
# ==========================================
import asyncio
import json

import websockets

from app.config import BOARD_TOOL, DASHSCOPE_WS_URL, build_ssl_context, get_api_key

INSTRUCTIONS = (
    "你是法语老师。用户要求写黑板时，先口头讲一句，"
    "再调用 write_to_board 工具；工具返回后继续口头总结。"
)


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
# 单个场景：连接、配置 modalities、发文字请求、读一轮 response
# ==========================================
async def run_case(name: str, modalities: list) -> None:
    """
    在指定 modalities 下请求模型写黑板，报告是否触发工具调用。
    Args:
        name: 场景名 (str)
        modalities: session modalities 列表 (list)
    """
    print(f"== 场景 {name}: modalities={modalities} ==")
    headers = {"Authorization": f"Bearer {get_api_key()}"}
    audio_sec = 0.0
    text = ""
    tool_call = None
    session_echo = None
    async with websockets.connect(
        DASHSCOPE_WS_URL, additional_headers=headers, ssl=build_ssl_context()
    ) as ws:
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "modalities": modalities,
                "instructions": INSTRUCTIONS,
                "tools": [BOARD_TOOL],
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

        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=30)
            ev = json.loads(raw)
            etype = ev.get("type", "")
            if etype == "session.updated":
                sess = ev.get("session", {})
                session_echo = {
                    "modalities": sess.get("modalities"),
                    "tools": [t.get("function", {}).get("name") for t in sess.get("tools", []) or []],
                }
            elif etype == "response.audio.delta":
                audio_sec += b64_seconds(ev.get("delta", ""))
            elif etype in ("response.audio_transcript.delta", "response.text.delta"):
                text += ev.get("delta", "")
            elif etype == "response.function_call_arguments.done":
                tool_call = {
                    "name": ev.get("name", ""),
                    "arguments": ev.get("arguments", "")[:80],
                }
            elif etype == "error":
                print("  ERROR:", json.dumps(ev, ensure_ascii=False)[:400])
            elif etype == "response.done":
                break

    print("  session.updated 回显:", session_echo)
    print("  口头字幕:", text[:80])
    print("  语音时长:", round(audio_sec, 2), "秒")
    print("  工具调用:", tool_call if tool_call else "未触发 ❌")
    print()


# ==========================================
# 主流程：依次跑两个场景
# ==========================================
async def main() -> None:
    """
    对比仅语音与语音+文字两种 modalities 下的工具调用行为。
    """
    await run_case("A 仅语音", ["audio"])
    await run_case("B 语音+文字", ["text", "audio"])


if __name__ == "__main__":
    asyncio.run(main())
