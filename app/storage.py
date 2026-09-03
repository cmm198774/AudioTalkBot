# ==========================================
# 本地 JSON 持久化：会话与预设的增删改查
# ==========================================
import json
import threading
import uuid
from datetime import datetime

from app.config import PRESETS_FILE, SESSIONS_FILE

# 全局写锁，防止并发写入损坏文件
_LOCK = threading.Lock()

# update_session 允许修改的字段白名单
_SESSION_UPDATABLE_FIELDS = ("title", "system_prompt", "output_mode")


# ==========================================
# 通用 JSON 读取
# ==========================================
def _load(path, key: str) -> list:
    """
    读取 JSON 文件中的列表；文件不存在返回空列表。
    Args:
        path: JSON 文件路径 (Path)
        key: 顶层列表字段名 (str)
    Returns:
        list: 记录列表
    """
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get(key, [])


# ==========================================
# 通用 JSON 写入（原子替换）
# ==========================================
def _save(path, key: str, items: list) -> None:
    """
    将列表写入 JSON 文件，先写临时文件再替换，自动建目录。
    Args:
        path: JSON 文件路径 (Path)
        key: 顶层列表字段名 (str)
        items: 记录列表 (list)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({key: items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


# ==========================================
# 当前时间 ISO 字符串
# ==========================================
def _now() -> str:
    """
    返回当前时间的 ISO 格式字符串。
    Returns:
        str: 秒级精度 ISO 时间戳
    """
    return datetime.now().isoformat(timespec="seconds")


# ==========================================
# 会话：列表（按更新时间倒序）
# ==========================================
def list_sessions() -> list:
    """
    返回所有会话，按 updated_at 倒序。
    Returns:
        list: 会话字典列表
    """
    sessions = _load(SESSIONS_FILE, "sessions")
    return sorted(sessions, key=lambda s: s.get("updated_at", ""), reverse=True)


# ==========================================
# 会话：创建
# ==========================================
def create_session(system_prompt: str, output_mode: str) -> dict:
    """
    创建新会话并落盘。
    Args:
        system_prompt: 该会话使用的 system prompt (str)
        output_mode: 输出模式 audio/text/audio_text (str)
    Returns:
        dict: 新建的会话记录
    """
    session = {
        "id": uuid.uuid4().hex,
        "title": "新对话",
        "created_at": _now(),
        "updated_at": _now(),
        "system_prompt": system_prompt,
        "output_mode": output_mode,
        "transcript": [],
    }
    with _LOCK:
        sessions = _load(SESSIONS_FILE, "sessions")
        sessions.append(session)
        _save(SESSIONS_FILE, "sessions", sessions)
    return session


# ==========================================
# 会话：按 id 读取
# ==========================================
def get_session(session_id: str) -> dict | None:
    """
    按 id 查找会话。
    Args:
        session_id: 会话 id (str)
    Returns:
        dict | None: 会话记录，不存在返回 None
    """
    for session in _load(SESSIONS_FILE, "sessions"):
        if session["id"] == session_id:
            return session
    return None


# ==========================================
# 会话：更新白名单字段
# ==========================================
def update_session(session_id: str, **fields) -> dict | None:
    """
    更新会话的白名单字段（title/system_prompt/output_mode），忽略其他字段。
    Args:
        session_id: 会话 id (str)
        **fields: 待更新字段
    Returns:
        dict | None: 更新后的会话，不存在返回 None
    """
    with _LOCK:
        sessions = _load(SESSIONS_FILE, "sessions")
        for session in sessions:
            if session["id"] == session_id:
                for name, value in fields.items():
                    if name in _SESSION_UPDATABLE_FIELDS and value is not None:
                        session[name] = value
                session["updated_at"] = _now()
                _save(SESSIONS_FILE, "sessions", sessions)
                return session
    return None


# ==========================================
# 会话：删除
# ==========================================
def delete_session(session_id: str) -> bool:
    """
    删除指定会话。
    Args:
        session_id: 会话 id (str)
    Returns:
        bool: 是否删除成功
    """
    with _LOCK:
        sessions = _load(SESSIONS_FILE, "sessions")
        remaining = [s for s in sessions if s["id"] != session_id]
        if len(remaining) == len(sessions):
            return False
        _save(SESSIONS_FILE, "sessions", remaining)
        return True


# ==========================================
# 会话：追加一条对话记录
# ==========================================
def append_transcript(session_id: str, role: str, text: str) -> dict | None:
    """
    向会话追加一条对话记录并更新时间戳。
    Args:
        session_id: 会话 id (str)
        role: user 或 assistant (str)
        text: 对话文本 (str)
    Returns:
        dict | None: 更新后的会话，不存在返回 None
    """
    with _LOCK:
        sessions = _load(SESSIONS_FILE, "sessions")
        for session in sessions:
            if session["id"] == session_id:
                session["transcript"].append({"role": role, "text": text, "ts": _now()})
                session["updated_at"] = _now()
                _save(SESSIONS_FILE, "sessions", sessions)
                return session
    return None
