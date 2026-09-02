# 语音对话机器人设计文档

- **日期**：2026-09-02
- **项目目录**：`G:\JupyterProject\20260902_Agent_法语学习`
- **状态**：已与用户确认

## 1. 项目概述

构建一个"像真人聊天一样"的语音对话机器人：接收语音输入、流式语音输出、支持随时打断，
system prompt 可自由定制。通用型机器人（不限场景，人设完全由 system prompt 决定）。

**核心决策**：用户已有端到端语音大模型 API（阿里云百炼 `qwen-audio-3.0-realtime-plus`），
无需 Pipecat / LiveKit Agents 等重型框架（它们面向"自行编排 ASR+LLM+TTS"场景），
自研轻量客户端是最合适方案，预计规模约后端 400 行 + 前端 400 行。

## 2. 依赖的模型与协议

- **模型**：`qwen-audio-3.0-realtime-plus`（阿里云百炼 / DashScope）
- **协议**：WebSocket（`wss://`）事件流，事件体系与 OpenAI Realtime API 高度相似：
  - 客户端事件：`session.update`（配置 system prompt / VAD / 输出模态）、
    `input_audio_buffer.append`（上行音频块）、`conversation.item.create`（注入历史）
  - 服务端事件：`session.created` / `session.updated`、`response.audio.delta`（下行音频）、
    `response.audio_transcript.delta`（回复字幕）、
    `conversation.item.input_audio_transcription.delta`（用户语音转写）、
    `input_audio_buffer.speech_started`（检测到用户开口，用于打断）、`response.done`、`error`
- **模型能力**：端到端（音频进、音频出）、服务端 VAD 端点检测、动态打断、毫秒级响应、
  可返回语音转写文本。
- **鉴权**：握手头 `Authorization: Bearer <API_KEY>`，端点
  `wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=<model>`。
- **音频格式**：输入 16kHz / 输出 24kHz，16bit、单声道 PCM，base64 编码。
- **限制**：`turn_detection` 只能在发送首个音频前修改（连接时设置一次即可）。

## 3. 需求清单（用户确认）

| 项目 | 结论 |
|------|------|
| 产品形态 | 本地网页：Python 后端 + 浏览器前端（手机同局域网也可访问） |
| 交互方式 | 全双工免提：点一次"开始对话"后免提聊天，可随时开口打断 |
| 输出模式 | 可选：仅语音 / 仅文字 / 语音+文字（对应 API modalities 配置） |
| 字幕 | 可开关，实时显示"我说的话"与"机器人回复" |
| system prompt | 网页设置面板编辑，保存后立即生效；支持多人设预设一键切换 |
| 会话管理 | 多会话：新建 / 切换 / 删除 / 重命名，本地存档，切回旧会话恢复上下文 |
| 使用场景 | 通用机器人（法语练习等均为可选用途，通过 prompt 实现） |

## 4. 总体架构

```
┌────────────────────────────┐        ┌─────────────────────────────┐        ┌──────────────────┐
│      浏览器前端 (单页面)      │  WS    │      Python 后端 (FastAPI)    │  WS    │  阿里云百炼        │
│                            │◄──────►│                             │◄──────►│  DashScope       │
│  麦克风采集 → 重采样 16kHz    │        │  双向桥接：                    │        │  qwen-audio-3.0- │
│  播放队列（可瞬间清空=打断）   │        │  · 上行音频 → input_audio_*   │        │  realtime-plus   │
│  字幕流 + 状态指示            │        │  · 下行音频 → 转发前端          │        │                  │
│  设置面板（prompt/输出模式）   │        │  · 转写字幕 → 广播前端          │        │  服务端 VAD       │
│  会话侧栏（增删切换）         │        │  会话/预设 本地持久化            │        │  动态打断         │
└────────────────────────────┘        └─────────────────────────────┘        └──────────────────┘
```

**职责划分**：

- **前端**：只管"声音进出 + 界面"，不接触 API key。
- **后端**：唯一与 DashScope 通信的角色——维护 WS 会话、注入 system prompt、
  转发音频、广播字幕、管理本地数据。
- **DashScope**：负责所有"智能"——听懂、思考、回答、服务端 VAD 判定说话结束、被打断时停止生成。

## 5. 数据流（一轮完整对话）

```
1. 用户点"开始对话"
   → 后端连 DashScope WS，发 session.update（system prompt + 服务端 VAD + 输出模态）
2. 用户说话
   → 前端每 ~100ms 发一个音频块 → 后端转成 input_audio_buffer.append 上传
3. 用户说完
   → 服务端 VAD 自动判定，开始生成回复（前端无需做任何判断）
4. 回复流式到达
   → response.audio.delta → 后端转发 → 前端排队播放（边收边播，低延迟）
   → 字幕文本增量 → 前端逐字显示
5. 打断
   → AI 说话时用户一开口 → 服务端发 speech_started
   → 后端立刻转告前端 → 前端瞬间清空播放队列 → 开始收新话语的回复
```

## 6. 后端设计（Python 3.10）

### 6.1 目录结构

```
20260902_Agent_法语学习/
├── app/
│   ├── main.py        # FastAPI 入口：页面托管、REST、WebSocket 端点
│   ├── bridge.py      # 核心：DashScope WS 桥接（事件循环、音频转发）
│   ├── storage.py     # 会话/预设的本地 JSON 持久化
│   ├── config.py      # API key 加载、模型名、音频参数
│   └── static/
│       ├── index.html
│       ├── app.js
│       └── style.css
├── data/              # 运行时生成：sessions.json、presets.json
├── docs/
├── tests/             # 单元测试
├── .env               # DASHSCOPE_API_KEY（gitignore）
├── .gitignore
├── requirements.txt   # fastapi、uvicorn、websockets、python-dotenv
└── README.md
```

### 6.2 bridge.py —— 核心桥接（每个活动对话一个实例）

| 职责 | 实现 |
|------|------|
| 建立会话 | 连 DashScope WS → 发 `session.update`（system prompt、服务端 VAD、输出模态） |
| 上行 | 前端音频块 → `input_audio_buffer.append` |
| 下行 | 事件分流：`response.audio.delta`→转发音频；`*_transcript.delta`→广播字幕；`response.done`→回合结束 |
| 打断 | 收到 `input_audio_buffer.speech_started` → 立即给前端发打断信号（优先级最高） |
| 恢复上下文 | 切换旧会话时，用 `conversation.item.create` 把存档的对话文本注入新会话 |

**操作语义明确**：

- 修改 prompt 后保存：后端对当前会话重发 `session.update` 即时生效，无需断开重连；
  同时更新该会话的 prompt 快照
- 切换会话：结束当前实时对话（断开 WS），载入目标会话存档；用户再次点"开始对话"
  时建立新连接并注入历史上下文
- 一键应用预设：把预设 prompt 填入文本框并按上一条规则保存生效

### 6.3 后端 ↔ 前端 WebSocket 消息协议（JSON）

```
前端 → 后端:
    {type: "audio", data: <base64 PCM>}
    {type: "start", session_id, system_prompt, output_mode}
    {type: "stop"}

后端 → 前端:
    {type: "audio", data: <base64 PCM>}        # 回复音频块
    {type: "interrupt"}                          # 立即清空播放队列
    {type: "transcript", role, delta}            # 字幕增量（role: user/assistant）
    {type: "state", value}                       # listening / thinking / speaking
    {type: "error", message}
```

### 6.4 REST 接口（会话与预设管理）

- `GET/POST /api/sessions`、`DELETE/PUT /api/sessions/{id}`（删除 / 重命名）
  - 新建会话标题先给默认值，用户首句字幕到达后自动更新
- `GET/POST/DELETE /api/presets`（人设预设）

## 7. 前端设计（单页面，原生 JS）

### 7.1 布局三区

- **左侧栏**：会话列表（➕新建 / 🗑删除 / 点击切换），当前会话高亮
- **中央**：字幕气泡流 + 状态指示球（听 / 想 / 说 三色状态）+ 开始/结束对话按钮
- **设置抽屉**：
  - system prompt 文本框（编辑 → 保存即生效）
  - 人设预设下拉（保存当前为预设 / 一键应用）
  - 输出模式（🔊仅语音 / 📝仅文字 / 语音+文字）
  - 字幕开关

### 7.2 两个音频模块（技术核心）

- **采集**：`getUserMedia`（开启 echoCancellation + noiseSuppression + autoGainControl）
  → AudioWorklet 中 48kHz→16kHz 重采样转 Int16 → 每 100ms 一块 base64 发后端
- **播放**：音频块解码（base64 → Int16 → Float32 → AudioBuffer）后进入队列，
  按时间戳预约连续播放（边收边播）；收到 `interrupt` 时
  stop 所有 source、清空队列、重置时间游标 → 打断即停

### 7.3 回声说明

外放喇叭时麦克风可能听到 AI 自己的声音造成误打断：默认开启浏览器回声消除，
界面提示"建议佩戴耳机以获得最佳体验"。

## 8. 数据存储

两个 JSON 文件，改动即写盘，启动时加载：

```json
// data/presets.json
{"presets": [{"id": "p1", "name": "法语老师", "prompt": "你是一位耐心的法语老师…"}]}

// data/sessions.json
{"sessions": [{
    "id": "uuid", "title": "首句自动命名",
    "created_at": "…", "updated_at": "…",
    "system_prompt": "本次会话实际使用的 prompt（快照）",
    "output_mode": "audio_text",
    "transcript": [
        {"role": "user", "text": "…", "ts": "…"},
        {"role": "assistant", "text": "…", "ts": "…"}
    ]
}]}
```

- 用户字幕到达后追加记录；assistant 回复按增量累积、回合结束（`response.done`）时整条落盘
- system prompt 存"会话快照"：修改预设不影响已有会话的历史语义

## 9. 错误处理

| 场景 | 处理 |
|------|------|
| API key 缺失/错误 | 启动时轻量校验，失败则页面 toast + 配置指引 |
| WS 断线（网络） | 前端检测 → 显示"已断开"横条 → 一键重连（自动注入历史恢复上下文） |
| DashScope 错误（限流/配额/内容过滤） | 转发错误事件 → toast 提示，会话不崩 |
| 麦克风权限被拒 | 开始按钮禁用 + 权限开启指引 |
| `conversation.item.create` 不受支持 | 降级：字幕存档照常显示，上下文从零开始，界面注明 |
| 未知协议事件 | 记日志忽略，不中断会话 |

## 10. 测试策略

**单元测试**（`tests/`，pytest，mock 掉真实 API）：

- storage：会话/预设 CRUD、文件读写
- bridge：事件分流逻辑（音频/字幕/打断/错误各走对通道）、历史注入的消息构造
- REST：FastAPI TestClient 测会话和预设接口

**手工验收清单**：

1. 说话→回复延迟体感流畅
2. 打断时 AI 声音立刻停止
3. 字幕与语音同步
4. 新建/切换/删除会话、旧会话上下文恢复
5. 断线重连
6. 输出模式切换（纯文字模式不发声）

## 11. 运行方式

```bash
# 依赖环境：conda py310
conda run -n py310 pip install -r requirements.txt
conda run -n py310 python -m uvicorn app.main:app --reload --port 8000
# 浏览器打开 http://localhost:8000
```

- API key 配置：项目根 `.env` 文件中 `DASHSCOPE_API_KEY=…`（已加入 .gitignore）

## 12. YAGNI 明确排除（v1 不做）

- 语音消息持久化音频文件（只存文字转写）
- 多用户 / 登录鉴权（本地个人工具）
- Live2D / 虚拟形象
- 移动端 App（浏览器手机访问即可）
- 历史会话全文搜索
