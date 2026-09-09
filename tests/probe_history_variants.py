# ==========================================
# 探针：测试哪种历史注入格式能让模型真正"记得"
# 变体 A: assistant + audio_transcript
# 变体 B: assistant + text
# 变体 C: user + input_text（摘要伪装成用户消息）
# 变体 D: 摘要写进 instructions（session.update）
# ==========================================
import asyncio
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import auth
from app.bridge import RealtimeBridge

SECRET = "BLUE-ELEPHANT-42"
QUESTION = ("What is the secret code mentioned earlier? "
            "Reply with ONLY the code, nothing else.")


# ==========================================
# 通用探测：注入事件 + 提问 + 检查回答
# ==========================================
async def probe(label: str, inject_events: list, instructions: str) -> bool:
    """
    连接真实 API，注入历史事件后提问密语。
    Args:
        label: 变体名称 (str)
        inject_events: connect 后手动发送的注入事件列表 (list)
        instructions: system prompt（变体 D 把摘要放这里） (str)
    Returns:
        bool: 模型是否答出密语
    """
    received = []

    async def send_to_client(msg):
        received.append(msg)

    async def on_final(role, text):
        pass

    creds = auth.decrypt_user_credentials("testuser")
    bridge = RealtimeBridge(
        send_to_client=send_to_client,
        on_final_transcript=on_final,
        api_key=creds["api_key"],
        base_url=creds["base_url"],
    )
    print(f"\n===== {label} =====")
    try:
        await bridge.connect(instructions, "text", history=None)
        for event in inject_events:
            await bridge._send_event(event)
        await asyncio.sleep(1)
        await bridge._send_event({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": QUESTION}],
            },
        })
        await bridge._send_event({
            "type": "response.create",
            "response": {"modalities": ["text"]},
        })
        answer = ""
        for _ in range(40):
            await asyncio.sleep(0.5)
            errors = [m for m in received if m.get("type") == "error"]
            if errors:
                print(f"ERROR events: {errors[:2]}")
                break
            answer = "".join(m.get("delta", "") for m in received
                             if m.get("type") == "transcript")
            if SECRET in answer:
                break
        ok = SECRET in answer
        print(f"answer: {answer[:150]!r}")
        print(f"RESULT: {'PASS' if ok else 'FAIL'}")
        return ok
    finally:
        await bridge.close()


# ==========================================
# 构造各变体的注入事件
# ==========================================
def item_event(role: str, content: dict) -> dict:
    """
    构造一条 conversation.item.create 事件。
    Args:
        role: 消息角色 (str)
        content: 内容块 (dict)
    Returns:
        dict: 事件字典
    """
    return {
        "type": "conversation.item.create",
        "item": {"type": "message", "role": role, "content": [content]},
    }


SUMMARY_TEXT = f"[对话摘要] The user's secret code is {SECRET}. The user loves French learning."


# ==========================================
# 入口：依次跑 4 个变体
# ==========================================
async def main() -> int:
    """
    运行全部变体并汇总。
    Returns:
        int: 始终返回 0（结果看输出）
    """
    results = {}
    results["A assistant+audio_transcript"] = await probe(
        "A: assistant + audio_transcript",
        [item_event("assistant", {"type": "audio_transcript", "transcript": SUMMARY_TEXT}),
         item_event("user", {"type": "input_text", "text": "OK, continue our lesson."})],
        "You are a helpful assistant.",
    )
    results["B assistant+text"] = await probe(
        "B: assistant + text",
        [item_event("assistant", {"type": "text", "text": SUMMARY_TEXT}),
         item_event("user", {"type": "input_text", "text": "OK, continue our lesson."})],
        "You are a helpful assistant.",
    )
    results["C user+input_text"] = await probe(
        "C: summary as user message",
        [item_event("user", {"type": "input_text", "text": SUMMARY_TEXT}),
         item_event("assistant", {"type": "audio_transcript", "transcript": "OK, I remember."})],
        "You are a helpful assistant.",
    )
    results["D instructions"] = await probe(
        "D: summary in instructions",
        [],
        "You are a helpful assistant.\n\n" + SUMMARY_TEXT,
    )
    print("\n===== SUMMARY =====")
    for k, v in results.items():
        print(f"{k}: {'PASS' if v else 'FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
