# ==========================================
# 检查 testuser 各会话的压缩状态与摘要内容
# ==========================================
import sys
import os
import json
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import storage

sessions = storage.list_sessions('testuser')
for s in sessions:
    full = storage.get_session('testuser', s['id'])
    t = full.get('transcript', [])
    chars = sum(len(i.get('text', '')) for i in t)
    sum_items = [i for i in t if i.get('text', '').startswith('[对话摘要]')]
    print(f"id={s['id']} title={full.get('title', '')[:25]!r} "
          f"items={len(t)} chars={chars} summary={'YES' if sum_items else 'no'}")
    if sum_items:
        print(f"  summary_len={len(sum_items[0]['text'])}")
        print(f"  roles_after_summary={[i['role'] for i in t[t.index(sum_items[0]) + 1:]]}")
        print(f"  summary_head={sum_items[0]['text'][:120]!r}")
