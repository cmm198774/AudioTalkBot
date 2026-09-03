# ==========================================
# 上下文管理：用量估算、旧对话切分、LLM 摘要压缩
# 服务端超限时会静默丢弃旧历史，故在客户端主动压缩
# ==========================================
import logging

import httpx

from app.config import DASHSCOPE_BASE_URL, SUMMARY_MODEL, get_api_key

logger = logging.getLogger(__name__)

# realtime 模型最大输入约 16384 token，前端用量条以此为满格
CONTEXT_INPUT_LIMIT = 16000

# 压缩时最近多少条原样保留，其余部分合并为一条摘要
KEEP_RECENT = 6

# 摘要条目前缀：历史渲染与模型都能识别这是总结而非原话
SUMMARY_PREFIX = "[对话摘要] "

# 摘要系统提示词
_SUMMARY_SYSTEM_PROMPT = (
    "你是对话摘要助手。把给出的对话浓缩成一段简洁的摘要，"
    "保留重要事实、结论与约定，省略寒暄与重复内容，只输出摘要正文。"
)


# ==========================================
# 用量估算：各条文本字符数之和（近似 token 数）
# ==========================================
def estimate_tokens(transcript: list) -> int:
    """
    以字符总数近似上下文占用。
    Args:
        transcript: 对话记录列表 (list)
    Returns:
        int: 总字符数
    """
    return sum(len(item.get("text", "")) for item in transcript)


# ==========================================
# 切分可压缩的旧对话与需保留的近期对话
# ==========================================
def split_old_recent(transcript: list, keep_recent: int = KEEP_RECENT) -> tuple:
    """
    返回 (旧对话, 保留的近期对话)；记录数不超过 keep_recent 时旧对话为空。
    Args:
        transcript: 对话记录列表 (list)
        keep_recent: 原样保留的最近条数 (int)
    Returns:
        tuple: (旧对话列表, 近期对话列表)
    """
    if len(transcript) <= keep_recent:
        return [], list(transcript)
    return list(transcript[:-keep_recent]), list(transcript[-keep_recent:])


# ==========================================
# 组装摘要输入文本
# ==========================================
def build_summary_prompt(old_transcript: list) -> str:
    """
    把旧对话格式化成带角色前缀的对话文本，供摘要模型阅读。
    Args:
        old_transcript: 待总结的对话记录 (list)
    Returns:
        str: 对话文本
    """
    lines = []
    for item in old_transcript:
        role = "user" if item.get("role") == "user" else "assistant"
        lines.append(f"{role}: {item.get('text', '')}")
    return "\n".join(lines)


# ==========================================
# 合并摘要与近期对话为新历史
# ==========================================
def merge_compressed(summary_text: str, recent: list) -> list:
    """
    摘要作为新历史的第一条（助手视角），其后跟保留的近期对话。
    Args:
        summary_text: LLM 返回的摘要 (str)
        recent: 原样保留的对话记录 (list)
    Returns:
        list: 新的对话历史
    """
    entry = {"role": "assistant", "text": SUMMARY_PREFIX + summary_text.strip()}
    return [entry] + list(recent)


# ==========================================
# 调 OpenAI 兼容 chat/completions 生成摘要
# ==========================================
async def summarize_old_turns(old_transcript: list) -> str:
    """
    用文本模型把旧对话总结成一段摘要。
    Args:
        old_transcript: 待总结的对话记录 (list)
    Returns:
        str: 摘要正文
    Raises:
        httpx.HTTPError: 请求失败或状态码非 200
    """
    url = DASHSCOPE_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": SUMMARY_MODEL,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": build_summary_prompt(old_transcript)},
        ],
    }
    headers = {"Authorization": f"Bearer {get_api_key()}"}
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
