# ==========================================
# 上下文管理：用量估算、旧对话切分、LLM 摘要压缩
# 服务端超限时会静默丢弃旧历史，故在客户端主动压缩
# ==========================================
import logging

import httpx

from app.config import (
    DASHSCOPE_BASE_URL,
    SUMMARY_MODEL,
    build_ssl_context,
    get_api_key,
)

logger = logging.getLogger(__name__)

# realtime 模型最大输入约 16384 token，前端用量条以此为满格
CONTEXT_INPUT_LIMIT = 16000

# 压缩时最近多少条原样保留，其余部分合并为一条摘要
KEEP_RECENT = 6

# 摘要条目前缀：历史渲染与模型都能识别这是总结而非原话
SUMMARY_PREFIX = "[对话摘要] "

# 各语言的摘要系统提示词
_LANGUAGE_PROMPTS = {
    "zh": (
        "你是对话摘要助手。把给出的对话浓缩成一段简洁的摘要，"
        "保留重要事实、结论与约定，省略寒暄与重复内容，只输出摘要正文。"
    ),
    "en": (
        "You are a conversation summarizer. Condense the conversation into "
        "a concise summary, keeping important facts, conclusions and agreements, "
        "omitting pleasantries and repetitions. Output only the summary."
    ),
    "ja": (
        "あなたは会話要約アシスタントです。会話の内容を簡潔に要約し、"
        "重要な事実、結論、約束事を残し、挨拶や繰り返しを省略してください。"
        "要約本文のみを出力してください。"
    ),
    "ko": (
        "당신은 대화 요약 도우미입니다. 대화를 간결하게 요약하고, "
        "중요한 사실, 결론, 약속을 유지하며, 인사말과 반복 내용을 생략하세요. "
        "요약 본문만 출력하세요."
    ),
}

# 默认提示词（兼容未传 language 的情况）
_SUMMARY_SYSTEM_PROMPT = _LANGUAGE_PROMPTS["zh"]


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
# 检测对话文本的主要语言（按字符数投票）
# ==========================================
def detect_language(text: str) -> str:
    """
    遍历文本，按字符 Unicode 范围统计各语言字符数，返回最多的那个。
    支持 zh / en / ja / ko，无法判定时默认 zh。
    Args:
        text: 待检测文本 (str)
    Returns:
        str: 语言代码（zh / en / ja / ko）
    """
    counts = {"zh": 0, "ja": 0, "ko": 0, "en": 0}
    for ch in text:
        cp = ord(ch)
        # CJK 统一汉字 U+4E00 ~ U+9FFF
        if 0x4E00 <= cp <= 0x9FFF:
            counts["zh"] += 1
        # 日文平假名 U+3040 ~ U+309F 或 片假名 U+30A0 ~ U+30FF
        elif 0x3040 <= cp <= 0x30FF:
            counts["ja"] += 1
        # 韩文音节 U+AC00 ~ U+D7AF
        elif 0xAC00 <= cp <= 0xD7AF:
            counts["ko"] += 1
        # 拉丁字母（英语及其他西文）
        elif ch.isalpha() and cp < 0x0250:
            counts["en"] += 1
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else "zh"


# ==========================================
# 根据语言返回对应的摘要系统提示词
# ==========================================
def build_language_prompt(language: str) -> str:
    """
    返回指定语言的摘要系统提示词，未知语言回退到中文。
    Args:
        language: 语言代码（zh / en / ja / ko） (str)
    Returns:
        str: 系统提示词
    """
    return _LANGUAGE_PROMPTS.get(language, _LANGUAGE_PROMPTS["zh"])


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
async def summarize_old_turns(old_transcript: list, language: str = None) -> str:
    """
    用文本模型把旧对话总结成一段摘要。
    可指定语言，摘要将以该语言生成；未指定则使用中文。
    Args:
        old_transcript: 待总结的对话记录 (list)
        language: 目标语言代码（zh / en / ja / ko），None 默认中文 (str)
    Returns:
        str: 摘要正文
    Raises:
        httpx.HTTPError: 请求失败或状态码非 200
    """
    system_prompt = build_language_prompt(language or "zh")
    url = DASHSCOPE_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": SUMMARY_MODEL,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_summary_prompt(old_transcript)},
        ],
    }
    headers = {"Authorization": f"Bearer {get_api_key()}"}
    # 本环境默认证书库不可用，必须显式传 certifi 构造的 SSL 上下文
    async with httpx.AsyncClient(timeout=60, verify=build_ssl_context()) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
