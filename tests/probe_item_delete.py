# ==========================================
# 探针 F：验证 qwen-audio-3.0-realtime-plus 是否支持
# conversation.item.delete（会话内压缩方案 A 的前提）
# 步骤：
#   1. 注入一条含密语的 user 条目，记录 item_id
#   2. 发送 conversation.item.delete，看服务端是否确认
#      （conversation.item.deleted）还是返回 error 事件
#   3. 若删除成功，追问密语验证条目真的离开了模型上下文
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
    注入密语条目 → 删除 → 验证服务端行为与模型记忆。
    Returns:
        int: 0 支持删除且上下文生效，1 不支持或删除无效
    """
    received = []
    events = []
    done = asyncio.Event()

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

    # 间谍：捕获所有服务端原始事件（含 item.created / item.deleted）
    original_handle = bridge._handle_event

    async def spy(event):
        events.append(event)
        await original_handle(event)

    bridge._handle_event = spy

    try:
        await bridge.connect("You are a helpful assistant.", "text", history=None)

        # ---- 步骤 1：注入含密语的 user 条目 ----
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
        created = [e for e in events if e.get("type") == "conversation.item.created"]
        if not created:
            print("FAIL: 没收到 conversation.item.created，无法取得 item_id")
            print(f"收到的事件类型: {[e.get('type') for e in events]}")
            return 1
        item_id = created[-1]["item"]["id"]
        print(f"注入成功 item_id={item_id}")

        # ---- 步骤 2：发送删除事件 ----
        events.clear()
        await bridge._send_event({
            "type": "conversation.item.delete",
            "item_id": item_id,
        })
        deleted = False
        error = None
        for _ in range(20):
            await asyncio.sleep(0.5)
            deleted = any(e.get("type") == "conversation.item.deleted" for e in events)
            errs = [e for e in events if e.get("type") == "error"]
            if errs:
                error = errs[0].get("error", {})
            if deleted or error:
                break
        if error:
            print(f"FAIL: 服务端拒绝删除: {error}")
            return 1
        if not deleted:
            print(f"FAIL: 未收到确认，事件流: {[e.get('type') for e in events]}")
            return 1
        print("删除已确认: conversation.item.deleted")

        # ---- 步骤 3：追问密语，验证真的从上下文消失 ----
        events.clear()
        received.clear()
        await bridge._send_event({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": "What is my secret code? Reply with ONLY the code, "
                            "or reply UNKNOWN if you don't know it.",
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
            if any(e.get("type") == "response.done" for e in events):
                answer = "".join(m.get("delta", "") for m in received
                                 if m.get("type") == "transcript")
                break
        print(f"answer: {answer[:150]!r}")
        ok = SECRET not in answer
        print(f"RESULT: {'PASS - item.delete 可用且真正生效' if ok else 'FAIL - 删除后模型仍记得密语'}")
        return 0 if ok else 1
    finally:
        await bridge.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
