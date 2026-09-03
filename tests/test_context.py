# ==========================================
# 上下文管理测试：用量估算、新旧切分、摘要合并
# ==========================================
from app import context


# ==========================================
# 造 n 条交替角色的对话记录
# ==========================================
def make_transcript(n: int) -> list:
    """
    生成 n 条 user/assistant 交替的测试对话。
    Args:
        n: 记录条数 (int)
    Returns:
        list: 对话记录列表
    """
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "text": f"第{i}条"}
        for i in range(n)
    ]


# ==========================================
# 测试用量估算为各条文本字符数之和
# ==========================================
def test_estimate_tokens_sums_lengths():
    transcript = [{"role": "user", "text": "你好"}, {"role": "assistant", "text": "Bonjour"}]
    assert context.estimate_tokens(transcript) == 2 + 7
    assert context.estimate_tokens([]) == 0


# ==========================================
# 测试记录不超过保留条数时无可压缩部分
# ==========================================
def test_split_old_recent_short_returns_all_recent():
    transcript = make_transcript(6)
    old, recent = context.split_old_recent(transcript, keep_recent=6)
    assert old == []
    assert recent == transcript


# ==========================================
# 测试超出保留条数时旧对话被切出
# ==========================================
def test_split_old_recent_keeps_last_n():
    transcript = make_transcript(10)
    old, recent = context.split_old_recent(transcript, keep_recent=6)
    assert old == transcript[:4]
    assert recent == transcript[4:]


# ==========================================
# 测试摘要输入按角色格式化
# ==========================================
def test_build_summary_prompt_formats_roles():
    transcript = [{"role": "user", "text": "你好"}, {"role": "assistant", "text": "Bonjour"}]
    prompt = context.build_summary_prompt(transcript)
    assert "user: 你好" in prompt
    assert "assistant: Bonjour" in prompt


# ==========================================
# 测试摘要条目置于新历史最前
# ==========================================
def test_merge_compressed_prepends_summary():
    recent = [{"role": "user", "text": "最近一条"}]
    merged = context.merge_compressed("讨论了勾股定理", recent)
    assert len(merged) == 2
    assert merged[0]["role"] == "assistant"
    assert merged[0]["text"].startswith(context.SUMMARY_PREFIX)
    assert "讨论了勾股定理" in merged[0]["text"]
    assert merged[1] == {"role": "user", "text": "最近一条"}
