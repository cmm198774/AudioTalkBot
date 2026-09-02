# 语音对话机器人实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个本地网页版全双工语音对话机器人：麦克风输入 → qwen-audio-3.0-realtime-plus 端到端语音模型 → 流式语音播放，支持随时打断、字幕、system prompt 设置面板与多会话管理。

**Architecture:** Python FastAPI 后端作为浏览器与阿里云百炼 DashScope Realtime WebSocket 之间的桥接（后端是唯一接触 API key 的角色）；浏览器前端用 AudioWorklet 采集麦克风并重采样为 16kHz PCM 上传，用可瞬间清空的播放队列实现"打断即停"；会话与预设持久化到本地 JSON 文件。

**Tech Stack:** Python 3.10（conda py310）、FastAPI、uvicorn、websockets、pytest、pytest-asyncio、原生 HTML/CSS/JS（Web Audio API + AudioWorklet）。

**协议事实（已核实官方文档）：**
- 端点：`wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=<model>`
- 鉴权：握手头 `Authorization: Bearer <API_KEY>`
- 音频：输入 16kHz / 输出 24kHz，16bit 单声道 PCM，base64 编码
- 事件体系与 OpenAI Realtime 兼容；`turn_detection` 只能在发送首个音频前设置
- 若 `input_audio_transcription.model` 取值报错，按官方文档调整 `app/config.py` 中的 `TRANSCRIPTION_MODEL` 常量

**开发环境约定（用户全局规范）：**
- 所有 Python 命令通过 `conda run -n py310` 执行
- import 写在文件最顶部；`#` 分隔线+用途说明在 `def` 前，docstring 在 `def` 后（Args/Returns/Raises）
- def 内不嵌套 def（class 方法可以）；测试文件全部放 `tests/`
- Windows 环境，项目根目录：`G:\JupyterProject\20260902_Agent_法语学习`

---

## 文件结构

```
20260902_Agent_法语学习/
├── app/
│   ├── __init__.py              # 包标记（空文件）
│   ├── config.py                # 环境变量、模型常量、音频参数
│   ├── storage.py               # 会话/预设 JSON 持久化 CRUD
│   ├── protocol.py              # DashScope 事件构造纯函数
│   ├── bridge.py                # DashScope WS ↔ 浏览器 WS 桥接（异步）
│   ├── main.py                  # FastAPI 入口：静态页、REST、/ws/chat
│   └── static/
│       ├── index.html           # 页面骨架（侧栏/对话区/设置抽屉）
│       ├── style.css            # 样式
│       ├── audio.js             # 麦克风采集、播放队列、打断、base64 工具
│       ├── app.js               # 界面逻辑：会话/设置/字幕/状态/WS
│       └── capture-processor.worklet.js  # AudioWorklet：48k→16k 重采样
├── tests/
│   ├── conftest.py              # 存储隔离 fixture（autouse）
│   ├── test_config.py
│   ├── test_storage.py
│   ├── test_protocol.py
│   ├── test_bridge.py
│   └── test_api.py              # REST + WebSocket 端点测试
├── data/                        # 运行时生成（已 gitignore）
├── requirements.txt
├── pytest.ini
├── .env.example
├── .env                         # 用户自建，含真实 key（已 gitignore）
└── README.md
```

---

### Task 1: 项目骨架与配置模块

**Files:**
- Create: `requirements.txt`
- Create: `pytest.ini`
- Create: `.env.example`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 创建依赖与环境文件**

`requirements.txt`（锁定版本，py3.10 兼容）：

```
fastapi==0.115.6
uvicorn[standard]==0.32.1
websockets==14.1
python-dotenv==1.0.1
pytest==8.3.4
pytest-asyncio==0.24.0
httpx==0.27.2
```

`pytest.ini`：

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

`.env.example`：

```
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx
```

`app/__init__.py`：空文件。

安装依赖：

```bash
export PATH="/c/ProgramData/Anaconda3/Scripts:/c/ProgramData/Anaconda3:$PATH"
conda run -n py310 pip install -r requirements.txt
```

- [ ] **Step 2: 写失败的配置测试**

`tests/test_config.py`：

```python
# ==========================================
# 配置模块测试：常量正确性与环境变量读取
# ==========================================
from app import config


# ==========================================
# 测试音频参数与输出模式映射
# ==========================================
def test_audio_constants():
    assert config.INPUT_SAMPLE_RATE == 16000
    assert config.OUTPUT_SAMPLE_RATE == 24000
    assert config.AUDIO_CHUNK_MS == 100
    assert config.OUTPUT_MODE_MODALITIES["audio"] == ["audio"]
    assert config.OUTPUT_MODE_MODALITIES["text"] == ["text"]
    assert config.OUTPUT_MODE_MODALITIES["audio_text"] == ["text", "audio"]


# ==========================================
# 测试 WebSocket 地址包含模型名
# ==========================================
def test_ws_url_contains_model():
    assert config.DASHSCOPE_WS_URL.startswith("wss://dashscope.aliyuncs.com/api-ws/v1/realtime")
    assert config.MODEL_NAME in config.DASHSCOPE_WS_URL


# ==========================================
# 测试未设置环境变量时返回空串
# ==========================================
def test_get_api_key_missing(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    assert config.get_api_key() == ""


# ==========================================
# 测试环境变量存在时正常读取
# ==========================================
def test_get_api_key_present(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-123")
    assert config.get_api_key() == "sk-test-123"
```

- [ ] **Step 3: 运行测试确认失败**

```bash
conda run -n py310 python -m pytest tests/test_config.py -v
```

预期：`ModuleNotFoundError: No module named 'app.config'`（或 collection error）。

- [ ] **Step 4: 实现 config.py**

`app/config.py`：

```python
# ==========================================
# 全局配置：环境变量加载、模型常量、音频参数、路径
# ==========================================
import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录（app/ 的上一层）
BASE_DIR = Path(__file__).resolve().parent.parent

# 加载项目根 .env（内含 DASHSCOPE_API_KEY）
load_dotenv(BASE_DIR / ".env")

# ---- 模型与连接 ----
MODEL_NAME = "qwen-audio-3.0-realtime-plus"
DASHSCOPE_WS_URL = f"wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model={MODEL_NAME}"

# ---- 音频参数（官方协议：输入 16kHz、输出 24kHz、16bit 单声道 PCM）----
INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000
AUDIO_CHUNK_MS = 100

# ---- 输入转写模型（若服务端报错，按官方文档调整此常量）----
TRANSCRIPTION_MODEL = "qwen3-asr-flash"

# ---- 输出模式 → API modalities 映射 ----
OUTPUT_MODE_MODALITIES = {
    "audio": ["audio"],
    "text": ["text"],
    "audio_text": ["text", "audio"],
}

# ---- 数据持久化路径 ----
DATA_DIR = BASE_DIR / "data"
SESSIONS_FILE = DATA_DIR / "sessions.json"
PRESETS_FILE = DATA_DIR / "presets.json"


# ==========================================
# 读取 DashScope API Key
# ==========================================
def get_api_key() -> str:
    """
    从环境变量读取 API key。
    Returns:
        str: API key；未配置时返回空字符串
    """
    return os.getenv("DASHSCOPE_API_KEY", "")
```

- [ ] **Step 5: 运行测试确认通过**

```bash
conda run -n py310 python -m pytest tests/test_config.py -v
```

预期：4 个测试全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add requirements.txt pytest.ini .env.example app/__init__.py app/config.py tests/test_config.py
git commit -m "feat: 项目骨架与配置模块（模型常量、音频参数、API key 读取）"
```

---

### Task 2: 会话存储（storage.py 第一部分）

**Files:**
- Create: `app/storage.py`
- Create: `tests/conftest.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: 写存储隔离 fixture**

`tests/conftest.py`：

```python
# ==========================================
# pytest 公共 fixture：存储路径隔离
# ==========================================
import pytest

from app import storage


# ==========================================
# 所有测试自动使用临时数据目录，避免污染真实数据
# ==========================================
@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    """
    把 storage 模块的文件路径指向 pytest 临时目录。
    Args:
        tmp_path: pytest 内置临时目录 (Path)
        monkeypatch: pytest monkeypatch fixture
    """
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(storage, "PRESETS_FILE", tmp_path / "presets.json")
```

- [ ] **Step 2: 写失败的会话存储测试**

`tests/test_storage.py`：

```python
# ==========================================
# 存储模块测试：会话与预设的 CRUD 和持久化
# ==========================================
import json

from app import storage


# ==========================================
# 测试创建会话返回完整字段与默认值
# ==========================================
def test_create_session_defaults():
    session = storage.create_session("你是一个测试助手", "audio_text")
    assert session["title"] == "新对话"
    assert session["system_prompt"] == "你是一个测试助手"
    assert session["output_mode"] == "audio_text"
    assert session["transcript"] == []
    assert session["id"]
    assert session["created_at"]


# ==========================================
# 测试列表按更新时间倒序
# ==========================================
def test_list_sessions_sorted_by_updated_at():
    s1 = storage.create_session("", "audio_text")
    s2 = storage.create_session("", "audio_text")
    storage.update_session(s1["id"], title="改过的标题")
    sessions = storage.list_sessions()
    assert sessions[0]["id"] == s1["id"]
    assert sessions[1]["id"] == s2["id"]


# ==========================================
# 测试更新会话字段；未知 id 返回 None
# ==========================================
def test_update_session():
    session = storage.create_session("旧 prompt", "audio_text")
    updated = storage.update_session(
        session["id"], title="新标题", system_prompt="新 prompt", output_mode="text"
    )
    assert updated["title"] == "新标题"
    assert updated["system_prompt"] == "新 prompt"
    assert updated["output_mode"] == "text"
    assert storage.update_session("不存在", title="x") is None


# ==========================================
# 测试更新时拒绝非法字段
# ==========================================
def test_update_session_rejects_unknown_field():
    session = storage.create_session("", "audio_text")
    updated = storage.update_session(session["id"], transcript=[{"role": "user"}])
    assert updated["transcript"] == []


# ==========================================
# 测试删除会话
# ==========================================
def test_delete_session():
    session = storage.create_session("", "audio_text")
    assert storage.delete_session(session["id"]) is True
    assert storage.get_session(session["id"]) is None
    assert storage.delete_session(session["id"]) is False


# ==========================================
# 测试追加对话记录并更新时间戳
# ==========================================
def test_append_transcript():
    session = storage.create_session("", "audio_text")
    storage.append_transcript(session["id"], "user", "你好")
    storage.append_transcript(session["id"], "assistant", "Bonjour !")
    loaded = storage.get_session(session["id"])
    assert loaded["transcript"][0] == {
        "role": "user",
        "text": "你好",
        "ts": loaded["transcript"][0]["ts"],
    }
    assert loaded["transcript"][1]["text"] == "Bonjour !"
    assert len(loaded["transcript"]) == 2


# ==========================================
# 测试数据真实落盘
# ==========================================
def test_sessions_persist_to_disk(tmp_path):
    session = storage.create_session("落盘测试", "audio_text")
    raw = json.loads((tmp_path / "sessions.json").read_text(encoding="utf-8"))
    assert raw["sessions"][0]["id"] == session["id"]
```

- [ ] **Step 3: 运行测试确认失败**

```bash
conda run -n py310 python -m pytest tests/test_storage.py -v
```

预期：`ModuleNotFoundError: No module named 'app.storage'`。

- [ ] **Step 4: 实现 storage.py（会话部分）**

`app/storage.py`：

```python
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
```

- [ ] **Step 5: 运行测试确认通过**

```bash
conda run -n py310 python -m pytest tests/test_storage.py -v
```

预期：7 个测试全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add app/storage.py tests/conftest.py tests/test_storage.py
git commit -m "feat: 会话存储 CRUD 与 JSON 持久化"
```

---

### Task 3: 预设存储（storage.py 第二部分）

**Files:**
- Modify: `app/storage.py`（追加预设函数）
- Test: `tests/test_storage.py`（追加预设测试）

- [ ] **Step 1: 写失败的预设测试**

在 `tests/test_storage.py` 末尾追加：

```python
# ==========================================
# 测试预设的创建、列表、删除
# ==========================================
def test_presets_crud():
    preset = storage.create_preset("法语老师", "你是一位耐心的法语老师")
    assert preset["name"] == "法语老师"
    assert preset["prompt"] == "你是一位耐心的法语老师"
    assert len(storage.list_presets()) == 1
    assert storage.delete_preset(preset["id"]) is True
    assert storage.list_presets() == []
    assert storage.delete_preset(preset["id"]) is False
```

- [ ] **Step 2: 运行测试确认失败**

```bash
conda run -n py310 python -m pytest tests/test_storage.py::test_presets_crud -v
```

预期：`AttributeError: module 'app.storage' has no attribute 'create_preset'`。

- [ ] **Step 3: 实现预设函数**

在 `app/storage.py` 末尾追加：

```python
# ==========================================
# 预设：列表
# ==========================================
def list_presets() -> list:
    """
    返回所有预设。
    Returns:
        list: 预设字典列表
    """
    return _load(PRESETS_FILE, "presets")


# ==========================================
# 预设：创建
# ==========================================
def create_preset(name: str, prompt: str) -> dict:
    """
    创建人设预设并落盘。
    Args:
        name: 预设名称 (str)
        prompt: 预设的 system prompt 内容 (str)
    Returns:
        dict: 新建的预设记录
    """
    preset = {"id": uuid.uuid4().hex, "name": name, "prompt": prompt}
    with _LOCK:
        presets = _load(PRESETS_FILE, "presets")
        presets.append(preset)
        _save(PRESETS_FILE, "presets", presets)
    return preset


# ==========================================
# 预设：删除
# ==========================================
def delete_preset(preset_id: str) -> bool:
    """
    删除指定预设。
    Args:
        preset_id: 预设 id (str)
    Returns:
        bool: 是否删除成功
    """
    with _LOCK:
        presets = _load(PRESETS_FILE, "presets")
        remaining = [p for p in presets if p["id"] != preset_id]
        if len(remaining) == len(presets):
            return False
        _save(PRESETS_FILE, "presets", remaining)
        return True
```

- [ ] **Step 4: 运行测试确认通过**

```bash
conda run -n py310 python -m pytest tests/test_storage.py -v
```

预期：8 个测试全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add app/storage.py tests/test_storage.py
git commit -m "feat: 人设预设存储 CRUD"
```

---

### Task 4: 协议事件构造（protocol.py）

**Files:**
- Create: `app/protocol.py`
- Test: `tests/test_protocol.py`

- [ ] **Step 1: 写失败的协议测试**

`tests/test_protocol.py`：

```python
# ==========================================
# 协议模块测试：DashScope 事件 JSON 构造
# ==========================================
from app.protocol import (
    build_audio_append,
    build_history_events,
    build_session_update,
)


# ==========================================
# 测试 session.update 包含全部必要字段
# ==========================================
def test_build_session_update_full():
    event = build_session_update("你是法语老师", ["text", "audio"], voice="Cherry")
    assert event["type"] == "session.update"
    session = event["session"]
    assert session["instructions"] == "你是法语老师"
    assert session["modalities"] == ["text", "audio"]
    assert session["voice"] == "Cherry"
    assert session["input_audio_format"] == "pcm"
    assert session["output_audio_format"] == "pcm"
    assert session["turn_detection"] == {"type": "server_vad"}
    assert "model" in session["input_audio_transcription"]


# ==========================================
# 测试 voice 为空时省略该字段
# ==========================================
def test_build_session_update_no_voice():
    event = build_session_update("提示词", ["audio"], voice="")
    assert "voice" not in event["session"]


# ==========================================
# 测试音频追加事件
# ==========================================
def test_build_audio_append():
    event = build_audio_append("QUJD")
    assert event == {"type": "input_audio_buffer.append", "audio": "QUJD"}


# ==========================================
# 测试历史注入事件序列
# ==========================================
def test_build_history_events():
    transcript = [
        {"role": "user", "text": "你好"},
        {"role": "assistant", "text": "Bonjour"},
    ]
    events = build_history_events(transcript)
    assert len(events) == 2
    first = events[0]
    assert first["type"] == "conversation.item.create"
    assert first["item"]["type"] == "message"
    assert first["item"]["role"] == "user"
    assert first["item"]["content"] == [{"type": "input_text", "text": "你好"}]
    assert events[1]["item"]["role"] == "assistant"


# ==========================================
# 测试空历史返回空列表
# ==========================================
def test_build_history_events_empty():
    assert build_history_events([]) == []
```

- [ ] **Step 2: 运行测试确认失败**

```bash
conda run -n py310 python -m pytest tests/test_protocol.py -v
```

预期：`ModuleNotFoundError: No module named 'app.protocol'`。

- [ ] **Step 3: 实现 protocol.py**

`app/protocol.py`：

```python
# ==========================================
# DashScope Realtime 事件构造：纯函数，无 IO，便于单元测试
# ==========================================
from app.config import TRANSCRIPTION_MODEL


# ==========================================
# 构造 session.update 事件
# ==========================================
def build_session_update(instructions: str, modalities: list, voice: str = "") -> dict:
    """
    构造会话配置事件（system prompt、输出模态、服务端 VAD、输入转写）。
    Args:
        instructions: system prompt 内容 (str)
        modalities: 输出模态列表，如 ["text", "audio"] (list)
        voice: 发音人名称，空串表示使用默认 (str)
    Returns:
        dict: session.update 事件 JSON
    """
    session = {
        "modalities": modalities,
        "instructions": instructions,
        "input_audio_format": "pcm",
        "output_audio_format": "pcm",
        "input_audio_transcription": {"model": TRANSCRIPTION_MODEL},
        "turn_detection": {"type": "server_vad"},
    }
    if voice:
        session["voice"] = voice
    return {"type": "session.update", "session": session}


# ==========================================
# 构造音频追加事件
# ==========================================
def build_audio_append(b64_audio: str) -> dict:
    """
    构造上行音频块事件。
    Args:
        b64_audio: base64 编码的 PCM 音频 (str)
    Returns:
        dict: input_audio_buffer.append 事件 JSON
    """
    return {"type": "input_audio_buffer.append", "audio": b64_audio}


# ==========================================
# 构造单条历史消息注入事件
# ==========================================
def build_history_item(role: str, text: str) -> dict:
    """
    构造一条历史消息的注入事件（用于恢复会话上下文）。
    Args:
        role: user 或 assistant (str)
        text: 消息文本 (str)
    Returns:
        dict: conversation.item.create 事件 JSON
    """
    return {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": role,
            "content": [{"type": "input_text", "text": text}],
        },
    }


# ==========================================
# 构造完整历史注入事件序列
# ==========================================
def build_history_events(transcript: list) -> list:
    """
    将存档的对话记录转换为注入事件序列。
    Args:
        transcript: 对话记录列表，每项含 role 与 text (list)
    Returns:
        list: conversation.item.create 事件列表
    """
    return [build_history_item(item["role"], item["text"]) for item in transcript]
```

- [ ] **Step 4: 运行测试确认通过**

```bash
conda run -n py310 python -m pytest tests/test_protocol.py -v
```

预期：5 个测试全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add app/protocol.py tests/test_protocol.py
git commit -m "feat: DashScope Realtime 事件构造纯函数"
```

---

### Task 5: 实时桥接（bridge.py）

**Files:**
- Create: `app/bridge.py`
- Test: `tests/test_bridge.py`

- [ ] **Step 1: 写失败的桥接测试**

`tests/test_bridge.py`：

```python
# ==========================================
# 桥接模块测试：连接握手、事件分流、打断、转写持久化
# ==========================================
import json

from app.bridge import RealtimeBridge


# ==========================================
# 假 WebSocket：脚本化返回事件、记录发送内容
# ==========================================
class FakeWebSocket:
    def __init__(self, events: list):
        self._events = [json.dumps(e, ensure_ascii=False) for e in events]
        self.sent = []
        self.closed = False

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)

    async def close(self) -> None:
        self.closed = True


# ==========================================
# 创建桥接实例的测试工厂
# ==========================================
def make_bridge(fake_ws, url_holder, header_holder, received, finals):
    async def ws_factory(url, headers):
        url_holder.append(url)
        header_holder.append(headers)
        return fake_ws

    async def send_to_client(msg):
        received.append(msg)

    async def on_final_transcript(role, text):
        finals.append((role, text))

    return RealtimeBridge(
        send_to_client=send_to_client,
        on_final_transcript=on_final_transcript,
        api_key="sk-test",
        ws_factory=ws_factory,
    )


# ==========================================
# 测试连接时首先发送 session.update 且鉴权头正确
# ==========================================
async def test_connect_sends_session_update():
    fake_ws = FakeWebSocket([{"type": "session.created"}])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("你是法语老师", "audio_text", history=None)
    assert "Bearer sk-test" in headers[0]["Authorization"]
    assert "qwen-audio-3.0-realtime" in urls[0]
    first_sent = fake_ws.sent[0]
    assert first_sent["type"] == "session.update"
    assert first_sent["session"]["instructions"] == "你是法语老师"
    assert first_sent["session"]["modalities"] == ["text", "audio"]
    await bridge.close()


# ==========================================
# 测试带历史连接时注入 conversation.item.create
# ==========================================
async def test_connect_injects_history():
    fake_ws = FakeWebSocket([{"type": "session.created"}])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    history = [{"role": "user", "text": "你好"}, {"role": "assistant", "text": "Bonjour"}]
    await bridge.connect("", "audio_text", history=history)
    types = [e["type"] for e in fake_ws.sent]
    assert types.count("conversation.item.create") == 2
    await bridge.close()


# ==========================================
# 测试回复音频转发并进入 speaking 状态
# ==========================================
async def test_audio_delta_forwarded():
    fake_ws = FakeWebSocket([
        {"type": "response.created"},
        {"type": "response.audio.delta", "delta": "QUJD"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    assert {"type": "state", "value": "thinking"} in received
    assert {"type": "state", "value": "speaking"} in received
    assert {"type": "audio", "data": "QUJD"} in received
    await bridge.close()


# ==========================================
# 测试字幕增量累积，response.done 时产出最终转写
# ==========================================
async def test_transcript_accumulates_and_finalizes():
    fake_ws = FakeWebSocket([
        {"type": "response.audio_transcript.delta", "delta": "Bon"},
        {"type": "response.audio_transcript.delta", "delta": "jour"},
        {"type": "response.done"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    deltas = [m for m in received if m["type"] == "transcript" and m["role"] == "assistant"]
    assert [d["delta"] for d in deltas] == ["Bon", "jour"]
    assert finals == [("assistant", "Bonjour")]
    await bridge.close()


# ==========================================
# 测试用户开口打断：发出 interrupt 并切换 listening 状态
# ==========================================
async def test_speech_started_emits_interrupt():
    fake_ws = FakeWebSocket([
        {"type": "input_audio_buffer.speech_started"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    assert {"type": "interrupt"} in received
    assert {"type": "state", "value": "listening"} in received
    await bridge.close()


# ==========================================
# 测试用户语音转写完成事件
# ==========================================
async def test_user_transcription_completed():
    fake_ws = FakeWebSocket([
        {"type": "conversation.item.input_audio_transcription.completed", "transcript": "你好"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    user_msgs = [m for m in received if m["type"] == "transcript" and m["role"] == "user"]
    assert user_msgs[0]["delta"] == "你好"
    assert user_msgs[0]["final"] is True
    assert finals == [("user", "你好")]
    await bridge.close()


# ==========================================
# 测试错误事件转发为 error 消息
# ==========================================
async def test_error_event_forwarded():
    fake_ws = FakeWebSocket([
        {"type": "error", "error": {"message": "rate limited"}},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    errors = [m for m in received if m["type"] == "error"]
    assert errors[0]["message"] == "rate limited"
    await bridge.close()


# ==========================================
# 测试音频发送
# ==========================================
async def test_send_audio():
    fake_ws = FakeWebSocket([{"type": "session.created"}])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.send_audio("QUJD")
    assert {"type": "input_audio_buffer.append", "audio": "QUJD"} in fake_ws.sent
    await bridge.close()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
conda run -n py310 python -m pytest tests/test_bridge.py -v
```

预期：`ModuleNotFoundError: No module named 'app.bridge'`。

- [ ] **Step 3: 实现 bridge.py**

`app/bridge.py`：

```python
# ==========================================
# DashScope Realtime WebSocket 桥接：管理一个实时对话连接
# 上行：浏览器音频 → input_audio_buffer.append
# 下行：服务端事件分流 → 音频/字幕/打断/状态/错误
# ==========================================
import asyncio
import json
import logging

from websockets.asyncio.client import connect as ws_connect

from app.config import DASHSCOPE_WS_URL, OUTPUT_MODE_MODALITIES, get_api_key
from app.protocol import build_audio_append, build_history_events, build_session_update

logger = logging.getLogger(__name__)

# 已知但无需处理的服务端事件类型
_IGNORED_EVENTS = (
    "session.created",
    "session.updated",
    "input_audio_buffer.speech_stopped",
    "input_audio_buffer.committed",
    "response.output_item.added",
    "response.output_item.done",
    "response.content_part.added",
    "response.content_part.done",
    "response.audio.done",
    "response.audio_transcript.done",
    "response.text.done",
)


# ==========================================
# 实时对话桥接器
# ==========================================
class RealtimeBridge:
    """
    管理一条 DashScope Realtime 连接，把服务端事件翻译成前端消息。
    前端消息格式见设计文档 6.3 节：
        audio / interrupt / transcript / state / error
    """

    def __init__(self, send_to_client, on_final_transcript=None, api_key: str = "", ws_factory=None):
        """
        初始化桥接器。
        Args:
            send_to_client: 异步回调，把 dict 消息发给浏览器 (callable)
            on_final_transcript: 异步回调 (role, text)，最终转写落盘用 (callable)
            api_key: DashScope API key，缺省读环境变量 (str)
            ws_factory: 可注入的 WS 连接工厂，测试用 (callable)
        """
        self._send_to_client = send_to_client
        self._on_final_transcript = on_final_transcript
        self._api_key = api_key or get_api_key()
        self._ws_factory = ws_factory or self._default_ws_factory
        self._ws = None
        self._recv_task = None
        self._assistant_text = ""
        self._speaking = False

    # ==========================================
    # 默认 WebSocket 工厂（生产路径）
    # ==========================================
    async def _default_ws_factory(self, url: str, headers: dict):
        """
        建立真实的 DashScope WebSocket 连接。
        Args:
            url: WebSocket 地址 (str)
            headers: 握手头，含 Authorization (dict)
        Returns:
            WebSocket 连接对象
        """
        return await ws_connect(url, additional_headers=headers)

    # ==========================================
    # 建立连接并配置会话
    # ==========================================
    async def connect(self, instructions: str, output_mode: str, history=None) -> None:
        """
        连接 DashScope，发送 session.update，可选注入历史，然后启动接收循环。
        Args:
            instructions: system prompt (str)
            output_mode: audio / text / audio_text (str)
            history: 历史对话记录列表，用于恢复上下文 (list)
        """
        modalities = OUTPUT_MODE_MODALITIES.get(output_mode, ["text", "audio"])
        headers = {"Authorization": f"Bearer {self._api_key}"}
        self._ws = await self._ws_factory(DASHSCOPE_WS_URL, headers)
        await self._send_event(build_session_update(instructions, modalities))
        if history:
            for event in build_history_events(history):
                await self._send_event(event)
        self._recv_task = asyncio.create_task(self._recv_loop())

    # ==========================================
    # 上行：发送音频块
    # ==========================================
    async def send_audio(self, b64_audio: str) -> None:
        """
        转发一个音频块到 DashScope。
        Args:
            b64_audio: base64 编码的 PCM (str)
        """
        if self._ws is not None:
            await self._send_event(build_audio_append(b64_audio))

    # ==========================================
    # 热更新：重发 session.update（修改 prompt / 输出模式）
    # ==========================================
    async def update_session(self, instructions: str, output_mode: str) -> None:
        """
        不重连的情况下更新会话配置。
        Args:
            instructions: 新的 system prompt (str)
            output_mode: 新的输出模式 (str)
        """
        if self._ws is None:
            return
        modalities = OUTPUT_MODE_MODALITIES.get(output_mode, ["text", "audio"])
        await self._send_event(build_session_update(instructions, modalities))

    # ==========================================
    # 关闭连接与接收任务
    # ==========================================
    async def close(self) -> None:
        """
        取消接收任务并关闭 WebSocket。
        """
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    # ==========================================
    # 测试辅助：等待接收循环处理完脚本事件
    # ==========================================
    async def wait_recv_done(self) -> None:
        """
        等待接收任务自然结束（仅 FakeWebSocket 场景有意义）。
        """
        if self._recv_task is not None:
            await self._recv_task
            self._recv_task = None

    # ==========================================
    # 内部：发送事件
    # ==========================================
    async def _send_event(self, event: dict) -> None:
        """
        序列化事件并通过 WebSocket 发送。
        Args:
            event: 事件字典 (dict)
        """
        await self._ws.send(json.dumps(event, ensure_ascii=False))

    # ==========================================
    # 内部：向前端发消息
    # ==========================================
    async def _emit(self, msg: dict) -> None:
        """
        向前端发送一条消息。
        Args:
            msg: 前端消息字典 (dict)
        """
        await self._send_to_client(msg)

    # ==========================================
    # 内部：接收循环
    # ==========================================
    async def _recv_loop(self) -> None:
        """
        持续读取服务端事件并分流处理；连接异常时通知前端。
        """
        try:
            async for raw in self._ws:
                event = json.loads(raw)
                await self._handle_event(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("DashScope 连接异常: %s", exc)
            await self._emit({"type": "error", "message": f"连接已断开：{exc}"})

    # ==========================================
    # 内部：事件分流
    # ==========================================
    async def _handle_event(self, event: dict) -> None:
        """
        按事件类型分发处理。
        Args:
            event: 服务端事件字典 (dict)
        """
        etype = event.get("type", "")
        if etype == "response.audio.delta":
            await self._handle_audio_delta(event)
        elif etype in ("response.audio_transcript.delta", "response.text.delta"):
            await self._handle_transcript_delta(event)
        elif etype == "input_audio_buffer.speech_started":
            self._speaking = False
            await self._emit({"type": "interrupt"})
            await self._emit({"type": "state", "value": "listening"})
        elif etype == "response.created":
            await self._emit({"type": "state", "value": "thinking"})
        elif etype == "response.done":
            await self._handle_response_done()
        elif etype == "conversation.item.input_audio_transcription.completed":
            await self._handle_user_transcript(event)
        elif etype == "error":
            err = event.get("error", {})
            await self._emit({"type": "error", "message": err.get("message", str(err))})
        elif etype in _IGNORED_EVENTS:
            pass
        else:
            logger.debug("未处理的事件类型: %s", etype)

    # ==========================================
    # 内部：回复音频增量
    # ==========================================
    async def _handle_audio_delta(self, event: dict) -> None:
        """
        转发音频增量，首次到达时切换 speaking 状态。
        Args:
            event: response.audio.delta 事件 (dict)
        """
        delta = event.get("delta", "")
        if not delta:
            return
        if not self._speaking:
            self._speaking = True
            await self._emit({"type": "state", "value": "speaking"})
        await self._emit({"type": "audio", "data": delta})

    # ==========================================
    # 内部：回复文本增量（字幕）
    # ==========================================
    async def _handle_transcript_delta(self, event: dict) -> None:
        """
        转发字幕增量并累积到当前回合缓冲。
        Args:
            event: 字幕/文本增量事件 (dict)
        """
        delta = event.get("delta", "")
        if not delta:
            return
        self._assistant_text += delta
        await self._emit({"type": "transcript", "role": "assistant", "delta": delta, "final": False})

    # ==========================================
    # 内部：回合结束
    # ==========================================
    async def _handle_response_done(self) -> None:
        """
        回合结束：持久化累积的助手回复（含被打断时的部分回复），复位状态。
        """
        self._speaking = False
        if self._assistant_text and self._on_final_transcript is not None:
            await self._on_final_transcript("assistant", self._assistant_text)
        self._assistant_text = ""
        await self._emit({"type": "state", "value": "listening"})

    # ==========================================
    # 内部：用户语音转写完成
    # ==========================================
    async def _handle_user_transcript(self, event: dict) -> None:
        """
        转发用户最终转写并持久化。
        Args:
            event: input_audio_transcription.completed 事件 (dict)
        """
        text = event.get("transcript", "")
        if not text:
            return
        await self._emit({"type": "transcript", "role": "user", "delta": text, "final": True})
        if self._on_final_transcript is not None:
            await self._on_final_transcript("user", text)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
conda run -n py310 python -m pytest tests/test_bridge.py -v
```

预期：8 个测试全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add app/bridge.py tests/test_bridge.py
git commit -m "feat: DashScope Realtime 桥接器（事件分流、打断、转写回调）"
```

---

### Task 6: REST API（main.py 第一部分）

**Files:**
- Create: `app/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: 写失败的 REST 测试**

`tests/test_api.py`：

```python
# ==========================================
# HTTP API 测试：配置、会话、预设接口
# ==========================================
from fastapi.testclient import TestClient

from app import main


# ==========================================
# 测试首页返回 HTML
# ==========================================
def test_index_serves_html():
    client = TestClient(main.app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# ==========================================
# 测试配置接口字段
# ==========================================
def test_get_config():
    client = TestClient(main.app)
    data = client.get("/api/config").json()
    assert data["input_sample_rate"] == 16000
    assert data["output_sample_rate"] == 24000
    assert "has_api_key" in data
    assert "model" in data


# ==========================================
# 测试会话的创建、列表、更新、删除
# ==========================================
def test_sessions_crud():
    client = TestClient(main.app)
    created = client.post(
        "/api/sessions",
        json={"system_prompt": "测试提示词", "output_mode": "audio_text"},
    )
    assert created.status_code == 201
    sid = created.json()["id"]

    sessions = client.get("/api/sessions").json()
    assert any(s["id"] == sid for s in sessions)

    fetched = client.get(f"/api/sessions/{sid}").json()
    assert fetched["system_prompt"] == "测试提示词"

    updated = client.put(f"/api/sessions/{sid}", json={"title": "改名"}).json()
    assert updated["title"] == "改名"

    assert client.delete(f"/api/sessions/{sid}").status_code == 204
    assert client.get(f"/api/sessions/{sid}").status_code == 404
    assert client.delete(f"/api/sessions/{sid}").status_code == 404


# ==========================================
# 测试预设的创建、列表、删除
# ==========================================
def test_presets_crud():
    client = TestClient(main.app)
    created = client.post("/api/presets", json={"name": "法语老师", "prompt": "你是法语老师"})
    assert created.status_code == 201
    pid = created.json()["id"]
    assert len(client.get("/api/presets").json()) == 1
    assert client.delete(f"/api/presets/{pid}").status_code == 204
    assert client.delete(f"/api/presets/{pid}").status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

```bash
conda run -n py310 python -m pytest tests/test_api.py -v
```

预期：`ModuleNotFoundError: No module named 'app.main'`。

- [ ] **Step 3: 创建前端静态文件占位**

为避免 StaticFiles 目录不存在报错，先创建三个占位文件（后续任务填充完整内容）：

`app/static/index.html`：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>语音对话机器人</title>
</head>
<body>
    <p>占位页面，后续任务替换</p>
</body>
</html>
```

`app/static/style.css`、`app/static/audio.js`、`app/static/app.js`、`app/static/capture-processor.worklet.js`：均为空文件。

- [ ] **Step 4: 实现 main.py（REST 部分）**

`app/main.py`：

```python
# ==========================================
# FastAPI 入口：静态页面托管、会话/预设 REST 接口
# WebSocket 对话端点在后续任务中加入
# ==========================================
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import storage
from app.config import INPUT_SAMPLE_RATE, MODEL_NAME, OUTPUT_SAMPLE_RATE, get_api_key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="语音对话机器人")

# 静态资源目录与挂载
_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


# ==========================================
# 请求体模型
# ==========================================
class SessionCreate(BaseModel):
    system_prompt: str = ""
    output_mode: str = "audio_text"


class SessionUpdate(BaseModel):
    title: str | None = None
    system_prompt: str | None = None
    output_mode: str | None = None


class PresetCreate(BaseModel):
    name: str
    prompt: str


# ==========================================
# 首页
# ==========================================
@app.get("/")
async def index():
    """
    返回前端单页面。
    Returns:
        FileResponse: index.html
    """
    return FileResponse(_STATIC_DIR / "index.html")


# ==========================================
# 前端启动配置
# ==========================================
@app.get("/api/config")
async def get_config():
    """
    返回模型名、采样率、API key 是否已配置。
    Returns:
        dict: 前端初始化所需配置
    """
    return {
        "model": MODEL_NAME,
        "has_api_key": bool(get_api_key()),
        "input_sample_rate": INPUT_SAMPLE_RATE,
        "output_sample_rate": OUTPUT_SAMPLE_RATE,
    }


# ==========================================
# 会话：列表
# ==========================================
@app.get("/api/sessions")
async def list_sessions():
    """
    返回会话列表（按更新时间倒序）。
    Returns:
        list: 会话列表
    """
    return storage.list_sessions()


# ==========================================
# 会话：创建
# ==========================================
@app.post("/api/sessions", status_code=201)
async def create_session(body: SessionCreate):
    """
    创建新会话。
    Args:
        body: system_prompt 与 output_mode (SessionCreate)
    Returns:
        dict: 新会话
    """
    return storage.create_session(body.system_prompt, body.output_mode)


# ==========================================
# 会话：读取单个
# ==========================================
@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """
    读取单个会话。
    Args:
        session_id: 会话 id (str)
    Returns:
        dict: 会话
    """
    session = storage.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


# ==========================================
# 会话：更新
# ==========================================
@app.put("/api/sessions/{session_id}")
async def update_session(session_id: str, body: SessionUpdate):
    """
    更新会话标题、prompt 或输出模式。
    Args:
        session_id: 会话 id (str)
        body: 待更新字段 (SessionUpdate)
    Returns:
        dict: 更新后的会话
    """
    fields = body.model_dump(exclude_none=True)
    session = storage.update_session(session_id, **fields)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


# ==========================================
# 会话：删除
# ==========================================
@app.delete("/api/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str):
    """
    删除会话。
    Args:
        session_id: 会话 id (str)
    """
    if not storage.delete_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")


# ==========================================
# 预设：列表
# ==========================================
@app.get("/api/presets")
async def list_presets():
    """
    返回预设列表。
    Returns:
        list: 预设列表
    """
    return storage.list_presets()


# ==========================================
# 预设：创建
# ==========================================
@app.post("/api/presets", status_code=201)
async def create_preset(body: PresetCreate):
    """
    创建人设预设。
    Args:
        body: name 与 prompt (PresetCreate)
    Returns:
        dict: 新预设
    """
    return storage.create_preset(body.name, body.prompt)


# ==========================================
# 预设：删除
# ==========================================
@app.delete("/api/presets/{preset_id}", status_code=204)
async def delete_preset(preset_id: str):
    """
    删除预设。
    Args:
        preset_id: 预设 id (str)
    """
    if not storage.delete_preset(preset_id):
        raise HTTPException(status_code=404, detail="预设不存在")
```

- [ ] **Step 5: 运行测试确认通过**

```bash
conda run -n py310 python -m pytest tests/test_api.py -v
```

预期：4 个测试全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add app/main.py app/static tests/test_api.py
git commit -m "feat: FastAPI 应用与配置/会话/预设 REST 接口"
```

---

### Task 7: WebSocket 对话端点（main.py 第二部分）

**Files:**
- Modify: `app/main.py`（追加 /ws/chat 端点与桥接注入点）
- Test: `tests/test_api.py`（追加 WebSocket 测试）

- [ ] **Step 1: 写失败的 WebSocket 测试**

在 `tests/test_api.py` 末尾追加：

```python
# ==========================================
# 假桥接类：记录调用，模拟连接行为
# ==========================================
class FakeBridge:
    def __init__(self, send_to_client, on_final_transcript=None, api_key="", ws_factory=None):
        self.send_to_client = send_to_client
        self.on_final_transcript = on_final_transcript
        self.connected = None
        self.updated = None
        self.audio = []
        self.closed = False

    async def connect(self, instructions, output_mode, history=None):
        self.connected = (instructions, output_mode, history)
        # 触发一次用户最终转写，验证持久化回调与自动命名
        if self.on_final_transcript is not None:
            await self.on_final_transcript("user", "你好，这是自动命名测试")

    async def send_audio(self, b64_audio):
        self.audio.append(b64_audio)

    async def update_session(self, instructions, output_mode):
        self.updated = (instructions, output_mode)

    async def close(self):
        self.closed = True


# ==========================================
# 测试完整对话流程：start → 自动命名 → audio → update_settings → stop
# ==========================================
def test_ws_chat_flow(monkeypatch):
    holder = {}

    def fake_bridge_factory(**kwargs):
        bridge = FakeBridge(**kwargs)
        holder["bridge"] = bridge
        return bridge

    monkeypatch.setattr(main, "BRIDGE_CLASS", fake_bridge_factory)
    client = TestClient(main.app)

    sid = client.post(
        "/api/sessions",
        json={"system_prompt": "原有提示词", "output_mode": "audio_text"},
    ).json()["id"]

    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "start", "session_id": sid})
        # FakeBridge.connect 内触发用户转写 → 自动命名 → 后端推送 title
        title_msg = ws.receive_json()
        assert title_msg["type"] == "title"
        assert title_msg["value"] == "你好，这是自动命名测试"

        ws.send_json({"type": "audio", "data": "QUJD"})
        ws.send_json({
            "type": "update_settings",
            "system_prompt": "新提示词",
            "output_mode": "text",
        })
        ws.send_json({"type": "stop"})

    bridge = holder["bridge"]
    assert bridge.connected[0] == "原有提示词"
    assert bridge.connected[1] == "audio_text"
    assert bridge.audio == ["QUJD"]
    assert bridge.updated == ("新提示词", "text")
    assert bridge.closed is True

    session = client.get(f"/api/sessions/{sid}").json()
    assert session["title"] == "你好，这是自动命名测试"
    assert session["transcript"][0]["text"] == "你好，这是自动命名测试"
    assert session["system_prompt"] == "新提示词"
    assert session["output_mode"] == "text"


# ==========================================
# 测试 start 未知会话返回 error 消息
# ==========================================
def test_ws_chat_start_unknown_session(monkeypatch):
    monkeypatch.setattr(main, "BRIDGE_CLASS", FakeBridge)
    client = TestClient(main.app)
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "start", "session_id": "不存在"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "会话不存在" in msg["message"]


# ==========================================
# 连接失败的桥接类：模拟 API key 错误等握手失败
# ==========================================
class FailingBridge(FakeBridge):
    async def connect(self, instructions, output_mode, history=None):
        raise OSError("401 Unauthorized")


# ==========================================
# 测试连接 DashScope 失败时推送 error 消息而非直接断开
# ==========================================
def test_ws_chat_connect_failure(monkeypatch):
    monkeypatch.setattr(main, "BRIDGE_CLASS", FailingBridge)
    client = TestClient(main.app)
    sid = client.post("/api/sessions", json={}).json()["id"]
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "start", "session_id": sid})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "401" in msg["message"]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
conda run -n py310 python -m pytest tests/test_api.py -v
```

预期：新测试失败——`AttributeError: module 'app.main' has no attribute 'BRIDGE_CLASS'`。

- [ ] **Step 3: 实现 /ws/chat 端点**

在 `app/main.py` 顶部 import 区追加（保持 import 在最顶部）：

```python
from fastapi import WebSocket, WebSocketDisconnect

from app.bridge import RealtimeBridge
```

在文件末尾追加：

```python
# ==========================================
# 桥接类注入点（测试用假实现替换）
# ==========================================
BRIDGE_CLASS = RealtimeBridge


# ==========================================
# 对话 WebSocket 端点
# ==========================================
@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    """
    对话主通道：一个浏览器连接对应一个活动会话。
    前端消息：start / audio / update_settings / stop
    Args:
        ws: FastAPI WebSocket 连接
    """
    await ws.accept()
    bridge = None
    state = {"session_id": None}

    async def send_to_client(msg: dict) -> None:
        """
        把消息推送给浏览器。
        Args:
            msg: 前端消息字典 (dict)
        """
        await ws.send_json(msg)

    async def on_final_transcript(role: str, text: str) -> None:
        """
        最终转写落盘；首句用户发言自动命名会话。
        Args:
            role: user 或 assistant (str)
            text: 转写文本 (str)
        """
        session_id = state["session_id"]
        if not session_id:
            return
        storage.append_transcript(session_id, role, text)
        if role == "user":
            session = storage.get_session(session_id)
            if session is not None and session["title"] == "新对话":
                title = text.strip()[:20] or "新对话"
                storage.update_session(session_id, title=title)
                await send_to_client({"type": "title", "value": title})

    try:
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")
            if mtype == "start":
                if bridge is not None:
                    await bridge.close()
                session_id = msg.get("session_id")
                session = storage.get_session(session_id) if session_id else None
                if session is None:
                    await send_to_client({"type": "error", "message": "会话不存在"})
                    continue
                state["session_id"] = session_id
                bridge = BRIDGE_CLASS(
                    send_to_client=send_to_client,
                    on_final_transcript=on_final_transcript,
                )
                try:
                    await bridge.connect(
                        instructions=session["system_prompt"],
                        output_mode=session["output_mode"],
                        history=session["transcript"],
                    )
                except Exception as exc:
                    logger.warning("连接 DashScope 失败: %s", exc)
                    await bridge.close()
                    bridge = None
                    state["session_id"] = None
                    await send_to_client({"type": "error", "message": f"连接失败：{exc}"})
            elif mtype == "audio":
                if bridge is not None:
                    await bridge.send_audio(msg.get("data", ""))
            elif mtype == "update_settings":
                session_id = state["session_id"]
                system_prompt = msg.get("system_prompt")
                output_mode = msg.get("output_mode")
                if session_id:
                    fields = {}
                    if system_prompt is not None:
                        fields["system_prompt"] = system_prompt
                    if output_mode is not None:
                        fields["output_mode"] = output_mode
                    if fields:
                        storage.update_session(session_id, **fields)
                if bridge is not None:
                    await bridge.update_session(system_prompt or "", output_mode or "audio_text")
            elif mtype == "stop":
                if bridge is not None:
                    await bridge.close()
                    bridge = None
                state["session_id"] = None
    except WebSocketDisconnect:
        logger.info("前端 WebSocket 断开")
    finally:
        if bridge is not None:
            await bridge.close()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
conda run -n py310 python -m pytest tests/ -v
```

预期：全部测试 PASS（config 4 + storage 8 + protocol 5 + bridge 8 + api 7）。

- [ ] **Step 5: 提交**

```bash
git add app/main.py tests/test_api.py
git commit -m "feat: /ws/chat 对话端点（桥接生命周期、转写落盘、自动命名、热更新）"
```

---

### Task 8: 前端页面骨架（index.html + style.css）

**Files:**
- Modify: `app/static/index.html`（替换占位）
- Modify: `app/static/style.css`
- Test: `tests/test_api.py`（追加静态资源测试）

- [ ] **Step 1: 写静态资源测试**

在 `tests/test_api.py` 末尾追加：

```python
# ==========================================
# 测试静态 JS/CSS 资源可访问
# ==========================================
def test_static_assets_served():
    client = TestClient(main.app)
    for path in ("/static/style.css", "/static/audio.js", "/static/app.js", "/static/capture-processor.worklet.js"):
        assert client.get(path).status_code == 200, path
```

- [ ] **Step 2: 运行测试确认通过**（占位文件已存在，应直接通过）

```bash
conda run -n py310 python -m pytest tests/test_api.py::test_static_assets_served -v
```

预期：PASS。若失败检查 Task 6 Step 3 的占位文件是否创建。

- [ ] **Step 3: 实现 index.html**

`app/static/index.html`（整体替换）：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>语音对话机器人</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <div class="app">
        <!-- 左侧：会话列表 -->
        <aside class="sidebar">
            <div class="sidebar-header">
                <h1>会话</h1>
                <button id="new-session-btn" title="新建会话">＋</button>
            </div>
            <ul id="session-list"></ul>
            <div class="sidebar-footer">
                <button id="settings-btn">⚙ 设置</button>
            </div>
        </aside>

        <!-- 中央：对话区 -->
        <main class="main">
            <header class="main-header">
                <span id="session-title">未选择会话</span>
                <span id="status-dot" class="status-dot idle"></span>
                <span id="status-text">空闲</span>
            </header>
            <div id="transcript" class="transcript"></div>
            <div id="disconnect-banner" class="banner hidden">
                连接已断开
                <button id="reconnect-btn">重连</button>
            </div>
            <footer class="controls">
                <button id="talk-btn" class="talk-btn">🎙 开始对话</button>
            </footer>
        </main>

        <!-- 右侧抽屉：设置 -->
        <aside id="settings-drawer" class="drawer hidden">
            <div class="drawer-header">
                <h2>设置</h2>
                <button id="close-settings-btn">✕</button>
            </div>

            <label class="field-label" for="prompt-input">System Prompt（人设）</label>
            <textarea id="prompt-input" rows="8" placeholder="例如：你是一位耐心的法语老师，请用简单的法语和我对话，并在每句话后附上中文翻译。"></textarea>
            <div class="row">
                <button id="save-prompt-btn">保存并生效</button>
            </div>

            <label class="field-label" for="preset-select">人设预设</label>
            <div class="row">
                <select id="preset-select"></select>
                <button id="apply-preset-btn">应用</button>
                <button id="save-preset-btn">存为预设</button>
                <button id="delete-preset-btn">删除</button>
            </div>

            <label class="field-label">输出模式</label>
            <div class="row radio-row">
                <label><input type="radio" name="output-mode" value="audio_text" checked> 语音+文字</label>
                <label><input type="radio" name="output-mode" value="audio"> 仅语音</label>
                <label><input type="radio" name="output-mode" value="text"> 仅文字</label>
            </div>

            <label class="field-label">其他</label>
            <div class="row">
                <label><input type="checkbox" id="subtitle-toggle" checked> 显示字幕</label>
            </div>

            <p class="hint">建议佩戴耳机，避免外放声音被麦克风拾取造成误打断。</p>
            <p id="api-key-warning" class="hint warn hidden">
                ⚠ 未检测到 API Key：请在项目根目录 .env 中配置
                DASHSCOPE_API_KEY 后重启服务。
            </p>
        </aside>
    </div>

    <div id="toast" class="toast hidden"></div>

    <script src="/static/audio.js"></script>
    <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 4: 实现 style.css**

`app/static/style.css`（整体替换）：

```css
/* 深色主题布局：侧栏 + 对话区 + 设置抽屉 */

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    background: #14161a;
    color: #e6e6e6;
    height: 100vh;
    overflow: hidden;
}

.app {
    display: flex;
    height: 100vh;
}

/* ---- 左侧会话栏 ---- */
.sidebar {
    width: 240px;
    background: #1b1e24;
    border-right: 1px solid #2a2e36;
    display: flex;
    flex-direction: column;
}

.sidebar-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 16px;
}

.sidebar-header h1 {
    font-size: 16px;
}

#session-list {
    list-style: none;
    flex: 1;
    overflow-y: auto;
    padding: 4px 8px;
}

.session-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 12px;
    margin-bottom: 4px;
    border-radius: 8px;
    cursor: pointer;
    color: #c8ccd4;
}

.session-item:hover {
    background: #242832;
}

.session-item.active {
    background: #2d4a72;
    color: #ffffff;
}

.session-item .title {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.session-item .del-btn {
    background: none;
    border: none;
    color: #8a8f98;
    cursor: pointer;
    font-size: 14px;
}

.session-item .del-btn:hover {
    color: #ff6b6b;
}

.sidebar-footer {
    padding: 12px 16px;
    border-top: 1px solid #2a2e36;
}

/* ---- 中央对话区 ---- */
.main {
    flex: 1;
    display: flex;
    flex-direction: column;
}

.main-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 20px;
    border-bottom: 1px solid #2a2e36;
}

#session-title {
    font-weight: 600;
}

.status-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #555a63;
}

.status-dot.listening { background: #4caf50; }
.status-dot.thinking  { background: #ffb74d; }
.status-dot.speaking  { background: #42a5f5; }

#status-text {
    color: #9aa0aa;
    font-size: 13px;
}

.transcript {
    flex: 1;
    overflow-y: auto;
    padding: 20px 24px;
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.bubble {
    max-width: 72%;
    padding: 10px 14px;
    border-radius: 12px;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-word;
}

.bubble.user {
    align-self: flex-end;
    background: #2d4a72;
}

.bubble.assistant {
    align-self: flex-start;
    background: #23272f;
}

.banner {
    margin: 0 24px;
    padding: 8px 14px;
    background: #4a3333;
    border-radius: 8px;
    display: flex;
    gap: 10px;
    align-items: center;
}

.controls {
    padding: 16px;
    display: flex;
    justify-content: center;
}

.talk-btn {
    padding: 12px 36px;
    font-size: 16px;
    border: none;
    border-radius: 24px;
    background: #2d7ff9;
    color: #fff;
    cursor: pointer;
}

.talk-btn.talking {
    background: #d9534f;
}

/* ---- 设置抽屉 ---- */
.drawer {
    width: 340px;
    background: #1b1e24;
    border-left: 1px solid #2a2e36;
    padding: 16px;
    overflow-y: auto;
}

.drawer-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
}

.field-label {
    display: block;
    margin: 14px 0 6px;
    color: #9aa0aa;
    font-size: 13px;
}

#prompt-input {
    width: 100%;
    background: #14161a;
    color: #e6e6e6;
    border: 1px solid #2a2e36;
    border-radius: 8px;
    padding: 10px;
    resize: vertical;
}

.row {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
    margin-top: 6px;
}

.radio-row label {
    font-size: 13px;
}

select, button {
    background: #23272f;
    color: #e6e6e6;
    border: 1px solid #2a2e36;
    border-radius: 6px;
    padding: 6px 10px;
    cursor: pointer;
}

select {
    flex: 1;
}

button:hover {
    background: #2c313b;
}

.hint {
    margin-top: 14px;
    font-size: 12px;
    color: #8a8f98;
}

.hint.warn {
    color: #ffb74d;
}

.hidden {
    display: none !important;
}

/* ---- Toast ---- */
.toast {
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%);
    background: #333a45;
    color: #fff;
    padding: 10px 18px;
    border-radius: 8px;
    z-index: 99;
}
```

- [ ] **Step 5: 运行测试确认通过**

```bash
conda run -n py310 python -m pytest tests/test_api.py -v
```

预期：全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add app/static/index.html app/static/style.css tests/test_api.py
git commit -m "feat: 前端页面骨架（会话侧栏、对话区、设置抽屉）与样式"
```

---

### Task 9: 前端音频模块（audio.js + worklet）

**Files:**
- Modify: `app/static/capture-processor.worklet.js`（替换空文件）
- Modify: `app/static/audio.js`（替换空文件）

- [ ] **Step 1: 实现 AudioWorklet 重采样处理器**

`app/static/capture-processor.worklet.js`：

```javascript
// AudioWorklet 处理器：把麦克风音频（浏览器采样率，通常 48kHz）
// 线性插值重采样到 16kHz，按 100ms（1600 采样）一块输出 Int16 PCM

class CaptureProcessor extends AudioWorkletProcessor {
    constructor(options) {
        super();
        const opts = options.processorOptions || {};
        this.targetRate = opts.targetRate || 16000;
        this.chunkSize = opts.chunkSize || 1600;
        this.out = [];
        this.fraction = 0;
    }

    process(inputs) {
        const input = inputs[0];
        if (!input || !input[0]) {
            return true;
        }
        const frames = input[0];
        const ratio = sampleRate / this.targetRate;
        let i = this.fraction;
        while (i < frames.length) {
            const i0 = Math.floor(i);
            const i1 = Math.min(i0 + 1, frames.length - 1);
            const frac = i - i0;
            this.out.push(frames[i0] * (1 - frac) + frames[i1] * frac);
            if (this.out.length >= this.chunkSize) {
                this.emitChunk();
            }
            i += ratio;
        }
        this.fraction = i - frames.length;
        return true;
    }

    emitChunk() {
        const pcm = new Int16Array(this.chunkSize);
        for (let n = 0; n < this.chunkSize; n++) {
            const s = Math.max(-1, Math.min(1, this.out[n]));
            pcm[n] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        this.out = this.out.slice(this.chunkSize);
        this.port.postMessage({ pcm: pcm.buffer }, [pcm.buffer]);
    }
}

registerProcessor('capture-processor', CaptureProcessor);
```

- [ ] **Step 2: 实现 audio.js（采集 + 播放队列 + 打断 + base64 工具）**

`app/static/audio.js`：

```javascript
// 音频模块：麦克风采集（16kHz PCM 上传）、流式播放队列（可瞬间清空实现打断）
// 依赖全局变量 window.AUDIO_CONFIG = { input_sample_rate, output_sample_rate }（app.js 注入）

const AudioIO = {
    audioCtx: null,
    mediaStream: null,
    workletNode: null,
    playCtx: null,
    nextStartTime: 0,
    activeSources: new Set(),
    onChunk: null,

    // ==========================================
    // 启动麦克风采集，通过 onChunk(base64) 回调输出
    // ==========================================
    async startCapture(onChunk) {
        this.onChunk = onChunk;
        if (this.workletNode) {
            return;
        }
        this.mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
                channelCount: 1,
            },
        });
        this.audioCtx = new AudioContext();
        await this.audioCtx.audioWorklet.addModule('/static/capture-processor.worklet.js');
        const source = this.audioCtx.createMediaStreamSource(this.mediaStream);
        const inputRate = window.AUDIO_CONFIG.input_sample_rate;
        this.workletNode = new AudioWorkletNode(this.audioCtx, 'capture-processor', {
            processorOptions: {
                targetRate: inputRate,
                chunkSize: Math.floor(inputRate / 10),
            },
        });
        this.workletNode.port.onmessage = (e) => {
            if (this.onChunk) {
                this.onChunk(arrayBufferToBase64(e.data.pcm));
            }
        };
        // 经零增益节点挂到输出，保证 worklet 被调度但不发声
        const silent = this.audioCtx.createGain();
        silent.gain.value = 0;
        source.connect(this.workletNode);
        this.workletNode.connect(silent);
        silent.connect(this.audioCtx.destination);
    },

    // ==========================================
    // 停止采集并释放麦克风
    // ==========================================
    stopCapture() {
        if (this.workletNode) {
            this.workletNode.disconnect();
            this.workletNode.port.onmessage = null;
            this.workletNode = null;
        }
        if (this.mediaStream) {
            this.mediaStream.getTracks().forEach((t) => t.stop());
            this.mediaStream = null;
        }
        if (this.audioCtx) {
            this.audioCtx.close();
            this.audioCtx = null;
        }
        this.onChunk = null;
    },

    // ==========================================
    // 播放一个 base64 PCM 音频块（排队连续播放）
    // ==========================================
    playChunk(b64) {
        if (!this.playCtx) {
            this.playCtx = new AudioContext();
        }
        if (this.playCtx.state === 'suspended') {
            this.playCtx.resume();
        }
        const int16 = new Int16Array(base64ToArrayBuffer(b64));
        const float32 = new Float32Array(int16.length);
        for (let i = 0; i < int16.length; i++) {
            float32[i] = int16[i] / 32768;
        }
        const outRate = window.AUDIO_CONFIG.output_sample_rate;
        const buffer = this.playCtx.createBuffer(1, float32.length, outRate);
        buffer.copyToChannel(float32, 0);
        const source = this.playCtx.createBufferSource();
        source.buffer = buffer;
        source.connect(this.playCtx.destination);
        const startAt = Math.max(this.playCtx.currentTime, this.nextStartTime);
        source.start(startAt);
        this.nextStartTime = startAt + buffer.duration;
        this.activeSources.add(source);
        source.onended = () => this.activeSources.delete(source);
    },

    // ==========================================
    // 打断：立即停止所有播放并清空队列
    // ==========================================
    interrupt() {
        for (const source of this.activeSources) {
            try {
                source.stop();
            } catch (e) {
                // 已结束的 source 忽略
            }
        }
        this.activeSources.clear();
        this.nextStartTime = 0;
    },
};

// ==========================================
// ArrayBuffer → base64
// ==========================================
function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return btoa(binary);
}

// ==========================================
// base64 → ArrayBuffer
// ==========================================
function base64ToArrayBuffer(b64) {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    return bytes.buffer;
}
```

- [ ] **Step 3: 手工语法验证**

```bash
conda run -n py310 python -c "from pathlib import Path; import json; print('ok')"
node --check app/static/audio.js 2>nul || echo "无 node 环境则跳过语法检查，Task 12 浏览器验证"
```

预期：无语法错误（无 node 则跳过，最终以浏览器加载为准）。

- [ ] **Step 4: 提交**

```bash
git add app/static/audio.js app/static/capture-processor.worklet.js
git commit -m "feat: 前端音频模块（16kHz 采集、流式播放队列、打断即停）"
```

---

### Task 10: 前端界面逻辑（app.js）

**Files:**
- Modify: `app/static/app.js`（替换空文件）

- [ ] **Step 1: 实现 app.js**

`app/static/app.js`：

```javascript
// 界面逻辑：会话管理、设置面板、字幕渲染、状态指示、对话 WebSocket

// ==========================================
// 全局状态
// ==========================================
const state = {
    sessionId: null,
    sessions: [],
    presets: [],
    ws: null,
    talking: false,
    subtitleOn: true,
    currentAssistantBubble: null,
};

window.AUDIO_CONFIG = { input_sample_rate: 16000, output_sample_rate: 24000 };

const STATUS_TEXT = {
    idle: '空闲',
    listening: '在听…',
    thinking: '思考中…',
    speaking: '回答中…',
};

// ==========================================
// 通用 HTTP 请求
// ==========================================
async function api(path, options) {
    const opts = Object.assign({ headers: { 'Content-Type': 'application/json' } }, options || {});
    const resp = await fetch(path, opts);
    if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(`请求失败 ${resp.status}: ${detail}`);
    }
    if (resp.status === 204) {
        return null;
    }
    return resp.json();
}

// ==========================================
// Toast 提示
// ==========================================
function toast(message) {
    const el = document.getElementById('toast');
    el.textContent = message;
    el.classList.remove('hidden');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => el.classList.add('hidden'), 3000);
}

// ==========================================
// 状态指示
// ==========================================
function setStatus(value) {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    dot.className = `status-dot ${value}`;
    text.textContent = STATUS_TEXT[value] || value;
}

// ==========================================
// 字幕渲染
// ==========================================
function appendTranscript(role, delta, final) {
    if (!state.subtitleOn) {
        return;
    }
    const box = document.getElementById('transcript');
    if (role === 'assistant') {
        if (!state.currentAssistantBubble) {
            state.currentAssistantBubble = document.createElement('div');
            state.currentAssistantBubble.className = 'bubble assistant';
            box.appendChild(state.currentAssistantBubble);
        }
        state.currentAssistantBubble.textContent += delta;
    } else if (role === 'user' && final) {
        state.currentAssistantBubble = null;
        const bubble = document.createElement('div');
        bubble.className = 'bubble user';
        bubble.textContent = delta;
        box.appendChild(bubble);
    }
    box.scrollTop = box.scrollHeight;
}

// ==========================================
// 从历史记录渲染字幕（切换会话时）
// ==========================================
function renderTranscriptHistory(transcript) {
    const box = document.getElementById('transcript');
    box.innerHTML = '';
    state.currentAssistantBubble = null;
    for (const item of transcript) {
        const bubble = document.createElement('div');
        bubble.className = `bubble ${item.role}`;
        bubble.textContent = item.text;
        box.appendChild(bubble);
    }
    box.scrollTop = box.scrollHeight;
}

// ==========================================
// 对话 WebSocket 连接与消息处理
// ==========================================
function openWebSocket() {
    if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) {
        return;
    }
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    state.ws = new WebSocket(`${proto}://${location.host}/ws/chat`);
    state.ws.onopen = () => setBanner(false);
    state.ws.onclose = () => {
        setBanner(true);
        if (state.talking) {
            stopTalk();
        }
    };
    state.ws.onerror = () => toast('连接出错');
    state.ws.onmessage = (e) => handleServerMessage(JSON.parse(e.data));
}

function setBanner(visible) {
    document.getElementById('disconnect-banner').classList.toggle('hidden', !visible);
}

function handleServerMessage(msg) {
    switch (msg.type) {
        case 'audio':
            AudioIO.playChunk(msg.data);
            break;
        case 'interrupt':
            AudioIO.interrupt();
            setStatus('listening');
            break;
        case 'transcript':
            appendTranscript(msg.role, msg.delta, !!msg.final);
            break;
        case 'state':
            setStatus(msg.value);
            break;
        case 'title':
            renameCurrentSession(msg.value);
            break;
        case 'error':
            toast(msg.message);
            break;
    }
}

function sendWs(msg) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify(msg));
    }
}

// ==========================================
// 开始 / 结束对话
// ==========================================
async function startTalk() {
    if (!state.sessionId) {
        await newSession();
    }
    openWebSocket();
    try {
        await AudioIO.startCapture((b64) => {
            if (state.talking) {
                sendWs({ type: 'audio', data: b64 });
            }
        });
    } catch (err) {
        toast('无法访问麦克风，请检查浏览器权限');
        return;
    }
    state.talking = true;
    updateTalkButton();
    setStatus('listening');
    // WebSocket 可能仍在握手，等待打开后再发 start
    const waitOpen = () => new Promise((resolve) => {
        if (state.ws.readyState === WebSocket.OPEN) {
            resolve();
            return;
        }
        state.ws.addEventListener('open', () => resolve(), { once: true });
    });
    await waitOpen();
    sendWs({ type: 'start', session_id: state.sessionId });
}

function stopTalk() {
    state.talking = false;
    AudioIO.stopCapture();
    AudioIO.interrupt();
    sendWs({ type: 'stop' });
    setStatus('idle');
    updateTalkButton();
}

function updateTalkButton() {
    const btn = document.getElementById('talk-btn');
    if (state.talking) {
        btn.textContent = '⏹ 结束对话';
        btn.classList.add('talking');
    } else {
        btn.textContent = '🎙 开始对话';
        btn.classList.remove('talking');
    }
}

// ==========================================
// 会话管理
// ==========================================
async function loadSessions() {
    state.sessions = await api('/api/sessions');
    renderSessions();
}

function renderSessions() {
    const list = document.getElementById('session-list');
    list.innerHTML = '';
    for (const session of state.sessions) {
        const li = document.createElement('li');
        li.className = 'session-item' + (session.id === state.sessionId ? ' active' : '');

        const title = document.createElement('span');
        title.className = 'title';
        title.textContent = session.title;
        li.appendChild(title);

        const del = document.createElement('button');
        del.className = 'del-btn';
        del.textContent = '🗑';
        del.title = '删除会话';
        del.addEventListener('click', (e) => {
            e.stopPropagation();
            deleteSession(session.id);
        });
        li.appendChild(del);

        li.addEventListener('click', () => selectSession(session.id));
        list.appendChild(li);
    }
}

async function newSession() {
    const systemPrompt = document.getElementById('prompt-input').value;
    const outputMode = getOutputMode();
    const session = await api('/api/sessions', {
        method: 'POST',
        body: JSON.stringify({ system_prompt: systemPrompt, output_mode: outputMode }),
    });
    state.sessions.unshift(session);
    renderSessions();
    await selectSession(session.id);
}

async function selectSession(sessionId) {
    if (state.talking) {
        stopTalk();
    }
    state.sessionId = sessionId;
    const session = await api(`/api/sessions/${sessionId}`);
    document.getElementById('session-title').textContent = session.title;
    document.getElementById('prompt-input').value = session.system_prompt;
    setOutputMode(session.output_mode);
    renderTranscriptHistory(session.transcript);
    renderSessions();
}

async function deleteSession(sessionId) {
    await api(`/api/sessions/${sessionId}`, { method: 'DELETE' });
    if (state.sessionId === sessionId) {
        state.sessionId = null;
        document.getElementById('session-title').textContent = '未选择会话';
        document.getElementById('transcript').innerHTML = '';
    }
    await loadSessions();
}

function renameCurrentSession(title) {
    const session = state.sessions.find((s) => s.id === state.sessionId);
    if (session) {
        session.title = title;
    }
    document.getElementById('session-title').textContent = title;
    renderSessions();
}

// ==========================================
// 设置面板
// ==========================================
function getOutputMode() {
    const checked = document.querySelector('input[name="output-mode"]:checked');
    return checked ? checked.value : 'audio_text';
}

function setOutputMode(mode) {
    const radio = document.querySelector(`input[name="output-mode"][value="${mode}"]`);
    if (radio) {
        radio.checked = true;
    }
}

async function saveSettings() {
    if (!state.sessionId) {
        toast('请先创建或选择一个会话');
        return;
    }
    const systemPrompt = document.getElementById('prompt-input').value;
    const outputMode = getOutputMode();
    await api(`/api/sessions/${state.sessionId}`, {
        method: 'PUT',
        body: JSON.stringify({ system_prompt: systemPrompt, output_mode: outputMode }),
    });
    if (state.talking) {
        sendWs({ type: 'update_settings', system_prompt: systemPrompt, output_mode: outputMode });
    }
    toast('已保存，立即生效');
}

async function loadPresets() {
    state.presets = await api('/api/presets');
    renderPresetSelect();
}

function renderPresetSelect() {
    const select = document.getElementById('preset-select');
    select.innerHTML = '';
    for (const preset of state.presets) {
        const option = document.createElement('option');
        option.value = preset.id;
        option.textContent = preset.name;
        select.appendChild(option);
    }
}

function applyPreset() {
    const select = document.getElementById('preset-select');
    const preset = state.presets.find((p) => p.id === select.value);
    if (!preset) {
        toast('请先选择一个预设');
        return;
    }
    document.getElementById('prompt-input').value = preset.prompt;
    saveSettings();
}

async function savePreset() {
    const name = window.prompt('预设名称：');
    if (!name) {
        return;
    }
    const promptText = document.getElementById('prompt-input').value;
    await api('/api/presets', {
        method: 'POST',
        body: JSON.stringify({ name, prompt: promptText }),
    });
    await loadPresets();
    toast('预设已保存');
}

async function deletePreset() {
    const select = document.getElementById('preset-select');
    if (!select.value) {
        toast('请先选择一个预设');
        return;
    }
    await api(`/api/presets/${select.value}`, { method: 'DELETE' });
    await loadPresets();
}

// ==========================================
// 事件绑定与初始化
// ==========================================
function bindEvents() {
    document.getElementById('talk-btn').addEventListener('click', () => {
        if (state.talking) {
            stopTalk();
        } else {
            startTalk();
        }
    });
    document.getElementById('new-session-btn').addEventListener('click', newSession);
    document.getElementById('settings-btn').addEventListener('click', () => {
        document.getElementById('settings-drawer').classList.remove('hidden');
    });
    document.getElementById('close-settings-btn').addEventListener('click', () => {
        document.getElementById('settings-drawer').classList.add('hidden');
    });
    document.getElementById('save-prompt-btn').addEventListener('click', saveSettings);
    document.getElementById('apply-preset-btn').addEventListener('click', applyPreset);
    document.getElementById('save-preset-btn').addEventListener('click', savePreset);
    document.getElementById('delete-preset-btn').addEventListener('click', deletePreset);
    document.getElementById('reconnect-btn').addEventListener('click', () => {
        openWebSocket();
    });
    document.getElementById('subtitle-toggle').addEventListener('change', (e) => {
        state.subtitleOn = e.target.checked;
    });
    document.querySelectorAll('input[name="output-mode"]').forEach((radio) => {
        radio.addEventListener('change', saveSettings);
    });
}

window.addEventListener('DOMContentLoaded', async () => {
    try {
        const config = await api('/api/config');
        window.AUDIO_CONFIG.input_sample_rate = config.input_sample_rate;
        window.AUDIO_CONFIG.output_sample_rate = config.output_sample_rate;
        if (!config.has_api_key) {
            document.getElementById('api-key-warning').classList.remove('hidden');
        }
        await loadSessions();
        await loadPresets();
        bindEvents();
        if (state.sessions.length > 0) {
            await selectSession(state.sessions[0].id);
        }
    } catch (err) {
        toast(`初始化失败：${err.message}`);
    }
});
```

- [ ] **Step 2: 启动服务手工冒烟（仅验证页面加载，不验证对话）**

```bash
conda run -n py310 python -m uvicorn app.main:app --port 8000
```

浏览器打开 `http://localhost:8000`，预期：页面正常渲染（侧栏 + 对话区 + 设置按钮），按 F12 控制台无 JS 报错。验证后 `Ctrl+C` 停止。

- [ ] **Step 3: 提交**

```bash
git add app/static/app.js
git commit -m "feat: 前端界面逻辑（会话管理、设置热更新、字幕、状态指示）"
```

---

### Task 11: README 与运行说明

**Files:**
- Create: `README.md`

- [ ] **Step 1: 编写 README**

`README.md`：

````markdown
# 语音对话机器人

本地网页版全双工语音对话机器人：像和真人聊天一样说话，可随时开口打断。
后端对接阿里云百炼 `qwen-audio-3.0-realtime-plus` 端到端语音模型。

## 功能

- 全双工免提对话，开口即打断（服务端 VAD + 播放队列瞬间清空）
- 字幕可开关（用户语音转写 + 模型回复文本）
- 输出模式：语音 / 文字 / 语音+文字
- system prompt 设置面板：保存即生效，支持人设预设保存与切换
- 多会话管理：新建 / 切换 / 删除 / 自动命名，切换旧会话自动恢复上下文

## 快速开始

1. 准备 Python 3.10 环境（推荐 conda）：

    ```bash
    conda run -n py310 pip install -r requirements.txt
    ```

2. 配置 API key：复制 `.env.example` 为 `.env`，填入百炼 API key：

    ```
    DASHSCOPE_API_KEY=sk-xxxx
    ```

3. 启动：

    ```bash
    conda run -n py310 python -m uvicorn app.main:app --reload --port 8000
    ```

4. 浏览器打开 `http://localhost:8000`，新建会话 → 写好人设 → 点击"开始对话"。

## 测试

```bash
conda run -n py310 python -m pytest tests/ -v
```

## 架构

```
浏览器（麦克风 16kHz 采集 / 24kHz 流式播放 / 字幕 / 设置）
    ↕ WebSocket（/ws/chat）
FastAPI 后端（会话与预设持久化、鉴权隔离、事件分流）
    ↕ WebSocket（wss://dashscope.aliyuncs.com/api-ws/v1/realtime）
阿里云百炼 qwen-audio-3.0-realtime-plus（服务端 VAD、动态打断、转写）
```

设计文档：`docs/superpowers/specs/2026-09-02-voice-chat-bot-design.md`

## 常见问题

- **AI 说话时自己"打断自己"**：外放喇叭的回声被麦克风拾取所致。
  已默认开启浏览器回声消除；仍出现时请改用耳机。
- **字幕不出现**：检查 `app/config.py` 的 `TRANSCRIPTION_MODEL` 是否与
  官方文档一致；服务端报错会在页面 toast 中显示。
- **回复没有声音**：确认输出模式不是"仅文字"；浏览器自动播放策略要求
  先点击过"开始对话"按钮。
````

- [ ] **Step 2: 提交**

```bash
git add README.md
git commit -m "docs: README 运行说明与常见问题"
```

---

### Task 12: 端到端手工验收

**Files:** 无新文件（验收为主）

- [ ] **Step 1: 全量自动化测试**

```bash
conda run -n py310 python -m pytest tests/ -v
```

预期：全部通过（约 33 个测试）。

- [ ] **Step 2: 启动服务**

```bash
conda run -n py310 python -m uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 3: 按清单逐项手工验收**（浏览器 `http://localhost:8000`，建议戴耳机）

1. 新建会话，设置 prompt 为"你是一个友好的聊天伙伴"，点击开始对话，说一句"你好"
   → 预期：1~2 秒内 AI 语音回复，字幕同步显示双方文字
2. AI 长回复说到一半时开口说话
   → 预期：AI 声音立刻停止，开始响应新内容（打断生效）
3. 设置面板把输出模式改为"仅文字"并保存，再说一句话
   → 预期：回复只显示文字、不发声
4. 设置面板改 prompt 并保存（对话保持进行中），再说一句话
   → 预期：AI 立即按新人设回答（热更新生效，无需重连）
5. 把人设存为预设，再新建一个会话应用该预设
   → 预期：prompt 自动填入并生效
6. 新建第二个会话聊几句，切回第一个会话再聊
   → 预期：字幕历史正确显示；第一个会话的上下文仍在（可问"我刚才说我叫什么"验证）
7. 删除一个会话
   → 预期：列表移除，本地 `data/sessions.json` 同步更新
8. 拔掉网线（或禁用 Wi-Fi）几秒再恢复，点击"重连"
   → 预期：恢复后可继续对话
9. 若第 1 步字幕缺失：查看终端日志与页面 toast，按官方文档调整
   `app/config.py` 的 `TRANSCRIPTION_MODEL`，重启后重测

- [ ] **Step 4: 修复验收发现的问题**（如有）

每个问题修复后重新跑 `conda run -n py310 python -m pytest tests/ -v` 并提交：

```bash
git add <改动文件>
git commit -m "fix: <问题描述>"
```

- [ ] **Step 5: 验收通过后最终提交**（若工作区有残留改动）

```bash
git status
git add -A && git commit -m "chore: 端到端验收通过"
```
