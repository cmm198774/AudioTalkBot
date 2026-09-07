# ==========================================
# 探针：行为验证 create_response=false 是否真正生效
# 对照组：默认配置，发噪声 → 期望自动触发 response
# 实验组：create_response=false，发同样噪声 → 期望只提交不回复
# 用法：PYTHONPATH=. python tests/probe_vad_behavior.py
# ==========================================
import asyncio
import base64
import json
import random

import websockets

from app.config import DASHSCOPE_WS_URL, build_ssl_context, get_api_key

# 16kHz 16bit 单声道，100ms 一块
_CHUNK_SAMPLES = 1600


# ==========================================
# 生成一块噪声 / 静音 PCM 的 base64
# ==========================================
def noise_chunk(seed: int, silent: bool = False) -> str:
    """
    生成 100ms 的 PCM 块（噪声或静音）。
    Args:
        seed: 随机种子，保证两次运行一致 (int)
        silent: True 时生成静音块 (bool)
    Returns:
        str: base64 编码的 PCM
    """
    rng = random.Random(seed)
    if silent:
        samples = [0] * _CHUNK_SAMPLES
    else:
        samples = [rng.randint(-9000, 9000) for _ in range(_CHUNK_SAMPLES)]
    pcm = b"".join(s.to_bytes(2, "little", signed=True) for s in samples)
    return base64.b64encode(pcm).decode()


# ==========================================
# 收集一段时间内的事件类型序列
# ==========================================
async def collect_events(ws, seconds: float, stop_on: tuple) -> list:
    """
    读取事件直到超时或遇到终止事件。
    Args:
        ws: WebSocket 连接
        seconds: 最长收集秒数 (float)
        stop_on: 遇到即停止的事件类型 (tuple)
    Returns:
        list: 事件类型列表
    """
    types = []
    deadline = asyncio.get_event_loop().time() + seconds
    while True:
        remain = deadline - asyncio.get_event_loop().time()
        if remain <= 0:
            break
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remain)
        except asyncio.TimeoutError:
            break
        etype = json.loads(raw).get("type", "")
        types.append(etype)
        if etype in stop_on:
            break
    return types


# ==========================================
# 一个实验阶段：下发 VAD 配置 → 发噪声 → 收集事件
# ==========================================
async def run_phase(ws, name: str, turn_detection: dict) -> list:
    """
    配置 VAD、发送 1.2 秒噪声 + 3 秒静音，收集 12 秒内事件。
    Args:
        ws: WebSocket 连接
        name: 阶段名 (str)
        turn_detection: turn_detection 配置 (dict)
    Returns:
        list: 事件类型序列
    """
    await ws.send(json.dumps({
        "type": "session.update",
        "session": {"turn_detection": turn_detection},
    }))
    await collect_events(ws, 5, ("session.updated", "error"))
    for i in range(12):
        await ws.send(json.dumps({
            "type": "input_audio_buffer.append",
            "audio": noise_chunk(i),
        }))
    for i in range(30):
        await ws.send(json.dumps({
            "type": "input_audio_buffer.append",
            "audio": noise_chunk(100 + i, silent=True),
        }))
        await asyncio.sleep(0.1)
    types = await collect_events(ws, 12, ("response.done",))
    print(f"== {name} ==")
    print("  事件序列:", types)
    return types


# ==========================================
# 主流程：对照组 + 实验组
# ==========================================
async def main() -> None:
    """
    对照组期望出现 response.created；实验组若没有则 create_response 生效。
    """
    headers = {"Authorization": f"Bearer {get_api_key()}"}
    async with websockets.connect(
        DASHSCOPE_WS_URL, additional_headers=headers, ssl=build_ssl_context()
    ) as ws:
        await asyncio.wait_for(ws.recv(), timeout=20)  # session.created

        ctrl = await run_phase(ws, "对照组（默认自动回复）", {
            "type": "server_vad",
            "silence_duration_ms": 600,
        })
        # 对照组触发了回复就取消，避免浪费生成
        if "response.created" in ctrl:
            await ws.send(json.dumps({"type": "response.cancel"}))
            await collect_events(ws, 8, ("response.done",))

        test = await run_phase(ws, "实验组（create_response=false）", {
            "type": "server_vad",
            "silence_duration_ms": 600,
            "create_response": False,
        })

        ctrl_auto = "response.created" in ctrl
        test_auto = "response.created" in test
        print("\n结论:")
        print("  对照组自动触发回复:", ctrl_auto)
        print("  实验组自动触发回复:", test_auto)
        if ctrl_auto and not test_auto:
            print("  create_response=false 生效 ✅ 可实现后端决定是否回复")
        elif not ctrl_auto:
            print("  噪声未触发 VAD，本次无法判定（需要真人语音验证）")
        else:
            print("  create_response 被忽略 ❌ 只能靠调长静默窗口")


if __name__ == "__main__":
    asyncio.run(main())
