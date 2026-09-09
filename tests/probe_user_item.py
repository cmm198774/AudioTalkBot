# ==========================================
# 探针 E：仅注入 user + input_text 历史条目，
# 验证用户角色历史是否真的进入模型上下文
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


# ==========================================
# 主流程
# ==========================================
async def main() -> int:
    """
    注入 user input_text 历史后提问密语。
    Returns:
        int: 0 模型记得，1 不记得
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
    try:
        await bridge.connect("You are a helpful assistant.", "text", history=None)
        # 只注入一条 user 消息，密语藏在里面
        await bridge._send_event({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": f"Please remember: my secret code is {SECRET}.",
                }],
            },
        })
        await asyncio.sleep(1)
        await bridge._send_event({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": "What is my secret code? Reply with ONLY the code.",
                }],
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
        print(f"answer: {answer[:150]!r}")
        ok = SECRET in answer
        print(f"RESULT: {'PASS - user input_text history IS grounded' if ok else 'FAIL'}")
        return 0 if ok else 1
    finally:
        await bridge.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
