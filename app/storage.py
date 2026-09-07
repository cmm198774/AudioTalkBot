# ==========================================
# 本地 JSON 持久化：按用户隔离的会话与预设增删改查
# ==========================================
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

from app.config import get_user_data_dir

# 全局写锁，防止并发写入损坏文件
_LOCK = threading.Lock()

# update_session 允许修改的字段白名单
_SESSION_UPDATABLE_FIELDS = ("title", "system_prompt", "output_mode")


# ==========================================
# 获取用户专属的 sessions.json 路径
# ==========================================
def _get_sessions_file(username: str) -> Path:
    """
    返回用户的 sessions.json 路径。
    Args:
        username: 用户名 (str)
    Returns:
        Path: sessions.json 路径
    """
    return get_user_data_dir(username) / "sessions.json"


# ==========================================
# 获取用户专属的 presets.json 路径
# ==========================================
def _get_presets_file(username: str) -> Path:
    """
    返回用户的 presets.json 路径。
    Args:
        username: 用户名 (str)
    Returns:
        Path: presets.json 路径
    """
    return get_user_data_dir(username) / "presets.json"


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
def list_sessions(username: str) -> list:
    """
    返回指定用户的所有会话，按 updated_at 倒序。
    Args:
        username: 用户名 (str)
    Returns:
        list: 会话字典列表
    """
    sessions = _load(_get_sessions_file(username), "sessions")
    return sorted(sessions, key=lambda s: s.get("updated_at", ""), reverse=True)


# ==========================================
# 会话：创建
# ==========================================
def create_session(username: str, system_prompt: str, output_mode: str) -> dict:
    """
    创建新会话并落盘。
    Args:
        username: 用户名 (str)
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
        sessions = _load(_get_sessions_file(username), "sessions")
        sessions.append(session)
        _save(_get_sessions_file(username), "sessions", sessions)
    return session


# ==========================================
# 会话：按 id 读取
# ==========================================
def get_session(username: str, session_id: str) -> dict | None:
    """
    按 id 读取指定用户的会话。
    Args:
        username: 用户名 (str)
        session_id: 会话 id (str)
    Returns:
        dict | None: 会话记录，不存在返回 None
    """
    for session in _load(_get_sessions_file(username), "sessions"):
        if session["id"] == session_id:
            return session
    return None


# ==========================================
# 会话：更新白名单字段
# ==========================================
def update_session(username: str, session_id: str, **fields) -> dict | None:
    """
    更新会话的白名单字段（title/system_prompt/output_mode），忽略其他字段。
    Args:
        username: 用户名 (str)
        session_id: 会话 id (str)
        **fields: 待更新字段
    Returns:
        dict | None: 更新后的会话，不存在返回 None
    """
    with _LOCK:
        sessions = _load(_get_sessions_file(username), "sessions")
        for session in sessions:
            if session["id"] == session_id:
                for name, value in fields.items():
                    if name in _SESSION_UPDATABLE_FIELDS and value is not None:
                        session[name] = value
                session["updated_at"] = _now()
                _save(_get_sessions_file(username), "sessions", sessions)
                return session
    return None


# ==========================================
# 会话：删除
# ==========================================
def delete_session(username: str, session_id: str) -> bool:
    """
    删除指定用户的指定会话。
    Args:
        username: 用户名 (str)
        session_id: 会话 id (str)
    Returns:
        bool: 是否删除成功
    """
    with _LOCK:
        sessions = _load(_get_sessions_file(username), "sessions")
        remaining = [s for s in sessions if s["id"] != session_id]
        if len(remaining) == len(sessions):
            return False
        _save(_get_sessions_file(username), "sessions", remaining)
        return True


# ==========================================
# 会话：追加一条对话记录
# ==========================================
def append_transcript(username: str, session_id: str, role: str, text: str) -> dict | None:
    """
    向指定用户的会话追加一条对话记录并更新时间戳。
    Args:
        username: 用户名 (str)
        session_id: 会话 id (str)
        role: user 或 assistant (str)
        text: 对话文本 (str)
    Returns:
        dict | None: 更新后的会话，不存在返回 None
    """
    with _LOCK:
        sessions = _load(_get_sessions_file(username), "sessions")
        for session in sessions:
            if session["id"] == session_id:
                session["transcript"].append({"role": role, "text": text, "ts": _now()})
                session["updated_at"] = _now()
                _save(_get_sessions_file(username), "sessions", sessions)
                return session
    return None


# ==========================================
# 会话：整体替换对话历史（清空/压缩用）
# ==========================================
def replace_transcript(username: str, session_id: str, transcript: list) -> dict | None:
    """
    用新列表整体替换指定用户的会话对话历史。
    Args:
        username: 用户名 (str)
        session_id: 会话 id (str)
        transcript: 新的对话记录列表 (list)
    Returns:
        dict | None: 更新后的会话，不存在返回 None
    """
    with _LOCK:
        sessions = _load(_get_sessions_file(username), "sessions")
        for session in sessions:
            if session["id"] == session_id:
                session["transcript"] = list(transcript)
                session["updated_at"] = _now()
                _save(_get_sessions_file(username), "sessions", sessions)
                return session
    return None


# ==========================================
# 预设：列表
# ==========================================
def list_presets(username: str) -> list:
    """
    返回指定用户的所有预设。
    Args:
        username: 用户名 (str)
    Returns:
        list: 预设字典列表
    """
    return _load(_get_presets_file(username), "presets")


# ==========================================
# 预设：创建（同名覆盖）
# ==========================================
def create_preset(username: str, name: str, prompt: str) -> dict:
    """
    创建人设预设并落盘；若已存在同名预设，用新内容覆盖旧预设
    （保留原 id，不产生重复条目）。
    Args:
        username: 用户名 (str)
        name: 预设名称 (str)
        prompt: 预设的 system prompt 内容 (str)
    Returns:
        dict: 新建或被覆盖的预设记录
    """
    with _LOCK:
        presets = _load(_get_presets_file(username), "presets")
        for preset in presets:
            if preset["name"] == name:
                preset["prompt"] = prompt
                _save(_get_presets_file(username), "presets", presets)
                return preset
        preset = {"id": uuid.uuid4().hex, "name": name, "prompt": prompt}
        presets.append(preset)
        _save(_get_presets_file(username), "presets", presets)
    return preset


# ==========================================
# 预设：删除
# ==========================================
def delete_preset(username: str, preset_id: str) -> bool:
    """
    删除指定用户的指定预设。
    Args:
        username: 用户名 (str)
        preset_id: 预设 id (str)
    Returns:
        bool: 是否删除成功
    """
    with _LOCK:
        presets = _load(_get_presets_file(username), "presets")
        remaining = [p for p in presets if p["id"] != preset_id]
        if len(remaining) == len(presets):
            return False
        _save(_get_presets_file(username), "presets", remaining)
        return True
