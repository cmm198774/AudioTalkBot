# ==========================================
# 探针：验证 turn_detection 可配置字段是否被工作空间端点接受
# A) silence_duration_ms / threshold / prefix_padding_ms
#    （把"判定说完"的静默窗口拉长，解决学生磕巴被抢话）
# B) create_response: false
#    （服务端只提交音频不自动回复，后端决定是否触发 → 实现沉默）
# 用法：PYTHONPATH=. python tests/probe_vad.py
# ==========================================
import asyncio
import json

import websockets

from app.config import DASHSCOPE_WS_URL, build_ssl_context, get_api_key


# ==========================================
# 下发一种 turn_detection 配置，读取服务端响应
# ==========================================
async def try_config(ws, turn_detection: dict) -> dict:
    """
    发送 session.update 并等待 session.updated 或 error。
    Args:
        ws: WebSocket 连接
        turn_detection: turn_detection 配置字典 (dict)
    Returns:
        dict: {"accepted": bool, "echo": 服务端回传的配置或错误信息}
    """
    await ws.send(json.dumps({
        "type": "session.update",
        "session": {"turn_detection": turn_detection},
    }))
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=20)
        ev = json.loads(raw)
        etype = ev.get("type", "")
        if etype == "session.updated":
            return {
                "accepted": True,
                "echo": ev.get("session", {}).get("turn_detection"),
            }
        if etype == "error":
            return {"accepted": False, "echo": ev.get("error", {})}


# ==========================================
# 主流程：逐个探测字段支持情况
# ==========================================
async def main() -> None:
    """
    逐个下发配置并打印接受情况；回传配置里保留了字段才说明真正生效。
    """
    headers = {"Authorization": f"Bearer {get_api_key()}"}
    async with websockets.connect(
        DASHSCOPE_WS_URL, additional_headers=headers, ssl=build_ssl_context()
    ) as ws:
        raw = await asyncio.wait_for(ws.recv(), timeout=20)
        print("握手事件:", json.loads(raw).get("type"))

        cases = [
            ("A 静默窗口等字段", {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 1500,
            }),
            ("B create_response=false", {
                "type": "server_vad",
                "silence_duration_ms": 800,
                "create_response": False,
            }),
        ]
        for name, cfg in cases:
            result = await try_config(ws, cfg)
            print(f"\n== {name} ==")
            print("  accepted:", result["accepted"])
            print("  回传:", json.dumps(result["echo"], ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
