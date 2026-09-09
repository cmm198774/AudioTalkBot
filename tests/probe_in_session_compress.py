# ==========================================
# 探针 G：端到端验证"会话内压缩"真实生效
# 流程：
#   1. 连接时在历史笔记里埋密语 ALPHA-TIGER-1
#   2. 会话中注入一条 live 条目埋密语 BETA-PANDA-2
#   3. 验证模型两个密语都记得
#   4. compress_in_session：注入只含 ALPHA 的摘要 + 删除全部旧条目
#   5. 再问：ALPHA 应记得（来自摘要），BETA 应忘掉（条目已删）
# ==========================================
import asyncio
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import auth
from app.bridge import RealtimeBridge

SECRET_NOTE = "ALPHA-TIGER-1"   # 藏在历史笔记（压缩时被删除）
SECRET_LIVE = "BETA-PANDA-2"    # 藏在 live 条目（压缩时被删除）


# ==========================================
# 提一个文本问题并收集完整回答
# ==========================================
async def ask(bridge, events: list, received: list, question: str) -> str:
    """
    以 user 条目提问并触发文本回复，等待 response.done 后返回答案。
    Args:
        bridge: RealtimeBridge 实例 (RealtimeBridge)
        events: 原始事件收集列表 (list)
        received: 前端消息收集列表 (list)
        question: 问题文本 (str)
    Returns:
        str: 模型回答
    """
    events.clear()
    received.clear()
    await bridge._send_event({
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": question}],
        },
    })
    await bridge._send_event({
        "type": "response.create",
        "response": {"modalities": ["text"]},
    })
    for _ in range(60):
        await asyncio.sleep(0.5)
        errs = [e for e in events if e.get("type") == "error"]
        if errs:
            print(f"ERROR events: {errs[:2]}")
            return ""
        if any(e.get("type") == "response.done" for e in events):
            return "".join(m.get("delta", "") for m in received
                           if m.get("type") == "transcript")
    return ""


# ==========================================
# 主流程
# ==========================================
async def main() -> int:
    """
    端到端验证会话内压缩。
    Returns:
        int: 0 全部通过，1 失败
    """
    received = []
    events = []

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

    # 间谍：捕获所有服务端原始事件
    original_handle = bridge._handle_event

    async def spy(event):
        events.append(event)
        await original_handle(event)

    bridge._handle_event = spy

    try:
        # ---- 步骤 1：历史笔记埋密语 ----
        history = [{"role": "user", "text": f"Please remember: my first secret is {SECRET_NOTE}."}]
        await bridge.connect("You are a helpful assistant.", "text", history=history)
        await asyncio.sleep(1.5)
        if not bridge._note_item_id:
            print(f"FAIL: 历史笔记 item_id 未记录，事件: {[e.get('type') for e in events]}")
            return 1
        print(f"历史笔记 item_id={bridge._note_item_id}")

        # ---- 步骤 2：live 条目埋密语 ----
        await bridge._send_event({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": f"Please remember: my second secret is {SECRET_LIVE}.",
                }],
            },
        })
        await asyncio.sleep(1.5)
        if not bridge._live_items:
            print("FAIL: live 条目 item_id 未记录")
            return 1
        print(f"live 条目: {bridge._live_items}")

        # ---- 步骤 3：验证两个密语都记得 ----
        answer = await ask(bridge, events, received,
                           "What are my two secrets? Reply with ONLY the codes.")
        print(f"压缩前: {answer[:120]!r}")
        if SECRET_NOTE not in answer or SECRET_LIVE not in answer:
            print("FAIL: 压缩前模型就记不全密语，环境异常")
            return 1

        # ---- 步骤 4：会话内压缩（摘要只含第一个密语）----
        ok = await bridge.compress_in_session(
            f"Summary of earlier conversation: the user's first secret is {SECRET_NOTE}.",
            cutoff_marker=10 ** 6,
            delete_history_note=True,
        )
        if not ok:
            print("FAIL: compress_in_session 返回 False")
            return 1
        await asyncio.sleep(1.5)
        print(f"压缩后 live 条目: {bridge._live_items}，笔记: {bridge._note_item_id}")

        # ---- 步骤 5：第一个密语记得（摘要），第二个忘掉（已删除）----
        answer = await ask(bridge, events, received,
                           "What are my two secrets now? For each one reply with "
                           "the code, or UNKNOWN if you don't know it. "
                           "Format: FIRST=<code> SECOND=<code>")
        print(f"压缩后: {answer[:200]!r}")
        first_ok = SECRET_NOTE in answer
        second_ok = SECRET_LIVE not in answer
        if first_ok and second_ok:
            print("RESULT: PASS - 会话内压缩生效（摘要记得，删除忘掉，连接未断）")
            return 0
        print(f"RESULT: FAIL - first_ok={first_ok}, second_ok={second_ok}")
        return 1
    finally:
        await bridge.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
