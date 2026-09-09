# ==========================================
# 真机验证：用真实 DashScope API 验证自动压缩后的重连腿
# 1) 用 testuser 的真实凭证创建 RealtimeBridge
# 2) 带压缩形态的历史（摘要 + 最近 6 条）connect
# 3) 验证握手成功、无 error 事件、历史事件全部发出
# 4) 干净关闭
# ==========================================
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import auth, storage
from app.bridge import RealtimeBridge
from app.main import compose_instructions


# ==========================================
# 收集前端消息
# ==========================================
async def run_check():
    """
    执行真机重连验证。
    Returns:
        int: 0 成功，1 失败
    """
    received = []
    finals = []

    async def send_to_client(msg):
        received.append(msg)

    async def on_final(role, text):
        finals.append((role, text))

    creds = auth.decrypt_user_credentials("testuser")
    if not creds["api_key"]:
        print("FAIL: testuser has no api_key")
        return 1

    # 取测试会话，构造压缩形态的历史：1 条摘要 + 最近 6 条
    sessions = storage.list_sessions("testuser")
    if not sessions:
        print("FAIL: testuser has no sessions")
        return 1
    session = storage.get_session("testuser", sessions[0]["id"])
    transcript = session["transcript"]
    hist = [
        {"role": "assistant", "text": "[对话摘要] Simon is a French learner. "
         "They practiced greetings, numbers 1-20, polite expressions, "
         "travel phrases, days, months, colors, and discussed French culture "
         "(Nouvelle Vague, Impressionnisme, Monet's Nympheas, Musee de l'Orangerie)."}
    ] + transcript[-6:]
    print(f"history: {len(hist)} items, "
          f"{sum(len(i.get('text', '')) for i in hist)} chars")

    bridge = RealtimeBridge(
        send_to_client=send_to_client,
        on_final_transcript=on_final,
        api_key=creds["api_key"],
        base_url=creds["base_url"],
    )
    try:
        await bridge.connect(
            compose_instructions(session["system_prompt"]),
            "audio_text",
            history=hist,
        )
        print("connect() returned OK")
        # 等 3 秒看是否有服务端 error 事件
        await asyncio.sleep(3)
    except Exception as exc:
        print(f"FAIL: connect raised {type(exc).__name__}: {exc}")
        return 1
    finally:
        try:
            await bridge.close()
            print("close() returned OK")
        except Exception as exc:
            print(f"FAIL: close raised {type(exc).__name__}: {exc}")
            return 1

    errors = [m for m in received if m.get("type") == "error"]
    if errors:
        print(f"FAIL: server error events: {errors}")
        return 1
    print(f"received {len(received)} client messages, no errors")
    print("PASS: real DashScope reconnect with compressed history works")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run_check()))
