# ==========================================
# 测试会话整理：删除旧测试会话，只保留本次新建的
# 压缩测试会话并改成醒目标题，方便前端选择
# ==========================================
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import storage

USERNAME = "testuser"
KEEP_ID = "f17350ec4f7e47929b2e50e8c791e3fe"
NEW_TITLE = "压缩测试-开口即触发"


# ==========================================
# 主流程
# ==========================================
def main():
    """
    删除 KEEP_ID 之外的全部 testuser 会话，并重命名保留的会话。
    """
    for session in storage.list_sessions(USERNAME):
        if session["id"] != KEEP_ID:
            storage.delete_session(USERNAME, session["id"])
            print(f"deleted: {session['id']} title={session['title']!r}")
    updated = storage.update_session(USERNAME, KEEP_ID, title=NEW_TITLE)
    chars = sum(len(i.get("text", "")) for i in updated["transcript"])
    print(f"kept: {KEEP_ID} title={NEW_TITLE!r} items={len(updated['transcript'])} chars={chars}")


if __name__ == "__main__":
    main()
