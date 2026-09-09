# ==========================================
# 探针：验证历史注入后模型是否真的"记得"注入内容
# 流程：带密语历史 connect → 文本提问密语 → 检查回答
# 同时捕获所有 error 事件（历史条目格式非法时 API 会报错）
# ==========================================
import asyncio
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import auth
from app.bridge import RealtimeBridge
from app.protocol import build_response_create

SECRET = "BLUE-ELEPHANT-42"


# ==========================================
# 主探针流程
# ==========================================
async def probe(history: list, label: str) -> bool:
    """
    用给定历史连接真实 API，提问密语，检查模型是否记得。
    Args:
        history: 注入的历史记录 (list)
        label: 本轮实验名称 (str)
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
        await bridge.connect("You are a helpful assistant.", "text", history=history)
        await asyncio.sleep(1)
        # 文本提问（conversation.item.create + response.create）
        await bridge._send_event({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": "What is the secret code mentioned earlier? Reply with ONLY the code.",
                }],
            },
        })
        await bridge._send_event({
            "type": "response.create",
            "response": {"modalities": ["text"]},
        })
        # 等待回复
        answer = ""
        for _ in range(40):
            await asyncio.sleep(0.5)
            texts = [m.get("delta", "") for m in received
                     if m.get("type") == "transcript"]
            answer = "".join(texts)
            errors = [m for m in received if m.get("type") == "error"]
            if errors:
                print(f"ERROR events: {errors}")
                break
            if SECRET in answer:
                break
        print(f"answer: {answer[:200]!r}")
        ok = SECRET in answer
        print(f"RESULT: {'PASS - model remembers injected history' if ok else 'FAIL - model does NOT know the secret'}")
        return ok
    finally:
        await bridge.close()


# ==========================================
# 入口：依次测试当前的 output_text 格式
# ==========================================
async def main() -> int:
    """
    运行探针。
    Returns:
        int: 0 全部通过，1 有失败
    """
    history = [
        {"role": "assistant", "text": f"[对话摘要] The user's secret code is {SECRET}. "
                                      "The user loves French learning."},
        {"role": "user", "text": "OK, continue our lesson."},
    ]
    ok = await probe(history, "current format (assistant=output_text)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
