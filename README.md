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

1. 准备 Python 3.10 环境（推荐 conda）。注意用 `python -m pip` 而非裸 `pip`，
   否则可能误用其他环境的解释器：

    ```bash
    conda run -n py310 python -m pip install -r requirements.txt
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
- **SSL / 证书报错**：某些 Windows + conda 环境下默认证书加载会失败。
  本项目已在 `app/bridge.py` 中显式用 `certifi` 证书构造 SSL 上下文，
  绕开系统证书库。若自行安装依赖遇到 `SSLEOFError`，优先使用
  `python -m pip install --cert <certifi/cacert.pem>`。
