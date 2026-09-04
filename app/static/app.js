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
    levelTimer: null,
    boardOn: true,
    boardRatio: 0.5,
    currentSession: null,
};

window.AUDIO_CONFIG = { input_sample_rate: 16000, output_sample_rate: 24000 };

// 模型最大输入约 16384 token，用量条以此为满格（字符数近似 token 数）
const CONTEXT_LIMIT = 16000;

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
function toast(message, durationMs) {
    const el = document.getElementById('toast');
    el.textContent = message;
    el.classList.remove('hidden');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => el.classList.add('hidden'), durationMs || 3000);
}

// ==========================================
// 麦克风权限预检：按浏览器当前授权状态给出明确提示
// ==========================================
async function promptMicPermission() {
    if (!navigator.permissions || !navigator.permissions.query) {
        return;
    }
    try {
        const status = await navigator.permissions.query({ name: 'microphone' });
        if (status.state === 'denied') {
            toast('麦克风权限已被浏览器拒绝。请点击地址栏左侧图标 → 站点设置 → 麦克风 → 改为"允许"，然后刷新页面重试。', 12000);
        } else if (status.state === 'prompt') {
            toast('即将请求麦克风权限，请在浏览器弹出的对话框中点击"允许"。', 5000);
        }
    } catch (e) {
        // 部分浏览器不支持查询麦克风权限状态，忽略
    }
}

// ==========================================
// 麦克风错误：把错误类型翻译成具体原因与解决指引
// ==========================================
function showMicError(err) {
    const name = err && err.name ? err.name : 'UnknownError';
    const guidance = {
        NotAllowedError: '麦克风权限被拒绝。点击地址栏左侧图标 → 站点设置 → 麦克风 → "允许"，然后刷新页面。',
        NotFoundError: '找不到麦克风设备。请确认耳机麦克风已连接并被系统识别。',
        NotReadableError: '麦克风被其他程序占用。请关闭占用麦克风的应用后重试。',
        SecurityError: '当前页面不是安全上下文，无法使用麦克风。请通过 http://localhost:8000 访问。',
    };
    const msg = guidance[name] || `麦克风错误（${name}）：${(err && err.message) || '请检查浏览器权限'}`;
    console.error('麦克风错误:', err);
    toast(msg, 12000);
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
// 小黑板：追加内容、清空、显隐、比例拖拽
// 新黑板段（new_segment）与已有内容之间空一行
// ==========================================
function appendBoard(delta, newSegment) {
    const content = document.getElementById('board-content');
    if (newSegment && content.textContent.length > 0) {
        content.textContent += '\n\n';
    }
    content.textContent += delta;
    content.scrollTop = content.scrollHeight;
}

function clearBoard() {
    document.getElementById('board-content').textContent = '';
}

// ==========================================
// 黑板与聊天区的高度比例：写 localStorage，刷新后恢复
// 面板按百分比定高，聊天区 flex:1 补齐余量
// ==========================================
function applyBoardRatio(ratio) {
    state.boardRatio = ratio;
    document.getElementById('board-panel').style.height = (ratio * 100).toFixed(1) + '%';
    try {
        localStorage.setItem('boardRatio', String(ratio));
    } catch (e) {
        // 隐私模式等场景下 localStorage 不可用，忽略
    }
}

function setBoardVisible(visible) {
    state.boardOn = visible;
    document.getElementById('board-panel').classList.toggle('hidden', !visible);
    document.getElementById('board-divider').classList.toggle('hidden', !visible);
    document.getElementById('board-toggle-btn').classList.toggle('active', visible);
    try {
        localStorage.setItem('boardOn', visible ? '1' : '0');
    } catch (e) {
        // 忽略
    }
}

// ==========================================
// 分割线拖拽：按住上下拖动调整两区比例（限制 15%~85%）
// ==========================================
function bindBoardDivider() {
    const divider = document.getElementById('board-divider');
    divider.addEventListener('mousedown', (e) => {
        e.preventDefault();
        divider.classList.add('dragging');
        document.body.classList.add('dragging-board');
        const rect = document.querySelector('.work-area').getBoundingClientRect();

        const onMove = (ev) => {
            if (rect.height <= 0) {
                return;
            }
            let ratio = (ev.clientY - rect.top) / rect.height;
            ratio = Math.min(0.85, Math.max(0.15, ratio));
            applyBoardRatio(ratio);
        };
        const onUp = () => {
            divider.classList.remove('dragging');
            document.body.classList.remove('dragging-board');
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    });
}

// ==========================================
// 黑板初始化：恢复比例与显隐偏好
// ==========================================
function initBoard() {
    let ratio = 0.5;
    try {
        const saved = parseFloat(localStorage.getItem('boardRatio'));
        if (saved > 0.1 && saved < 0.9) {
            ratio = saved;
        }
    } catch (e) {
        // 忽略
    }
    applyBoardRatio(ratio);
    let visible = true;
    try {
        visible = localStorage.getItem('boardOn') !== '0';
    } catch (e) {
        // 忽略
    }
    setBoardVisible(visible);
    bindBoardDivider();
}

// ==========================================
// 麦克风电平表：定时读取输入电平并显示
// 说话时条纹跳动 = 真的采到了声音
// ==========================================
function startLevelMeter() {
    const wrap = document.getElementById('mic-level');
    const bar = document.getElementById('mic-level-bar');
    wrap.classList.remove('hidden');
    clearInterval(state.levelTimer);
    state.levelTimer = setInterval(() => {
        const level = AudioIO.getInputLevel();
        // RMS 0~1，放大后映射到 0~100%
        const pct = Math.min(100, Math.round(level * 320));
        bar.style.width = pct + '%';
    }, 100);
}

function stopLevelMeter() {
    clearInterval(state.levelTimer);
    state.levelTimer = null;
    document.getElementById('mic-level').classList.add('hidden');
    document.getElementById('mic-level-bar').style.width = '0';
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
        const bubble = document.createElement('div');
        bubble.className = 'bubble user';
        bubble.textContent = delta;
        // 用户转写常晚于本轮回复开头到达：把问题气泡插到正在流式的
        // 助手气泡之前，保证"问题在回答前"，且回答不被切成两段
        if (state.currentAssistantBubble && state.currentAssistantBubble.parentNode === box) {
            box.insertBefore(bubble, state.currentAssistantBubble);
        } else {
            box.appendChild(bubble);
        }
    }
    box.scrollTop = box.scrollHeight;
}

// ==========================================
// 把混合回复文本拆成口头段与黑板段
// [start]...[end] 之间为黑板内容，其余为口头内容
// ==========================================
function splitBoardParts(text) {
    const parts = [];
    let rest = text;
    for (;;) {
        const start = rest.indexOf('[start]');
        if (start === -1) {
            if (rest) {
                parts.push({ kind: 'text', text: rest });
            }
            break;
        }
        if (start > 0) {
            parts.push({ kind: 'text', text: rest.slice(0, start) });
        }
        const end = rest.indexOf('[end]', start + '[start]'.length);
        if (end === -1) {
            const tail = rest.slice(start + '[start]'.length);
            if (tail) {
                parts.push({ kind: 'board', text: tail });
            }
            break;
        }
        const boardText = rest.slice(start + '[start]'.length, end);
        if (boardText) {
            parts.push({ kind: 'board', text: boardText });
        }
        rest = rest.slice(end + '[end]'.length);
    }
    return parts;
}

// ==========================================
// 从历史记录渲染字幕（切换会话时）
// 旧格式 [text]: 开头的助手消息整体渲染为板书气泡；
// 新格式含 [start]/[end] 的消息拆成口头气泡与 📋 板书气泡
// ==========================================
function renderTranscriptHistory(transcript) {
    const box = document.getElementById('transcript');
    box.innerHTML = '';
    state.currentAssistantBubble = null;
    for (const item of transcript) {
        if (item.role === 'assistant' && item.text.startsWith('[text]:')) {
            const bubble = document.createElement('div');
            bubble.className = 'bubble assistant board';
            bubble.textContent = '📋 ' + item.text.slice('[text]:'.length);
            box.appendChild(bubble);
        } else if (item.role === 'assistant' && item.text.includes('[start]')) {
            for (const part of splitBoardParts(item.text)) {
                const bubble = document.createElement('div');
                if (part.kind === 'board') {
                    bubble.className = 'bubble assistant board';
                    bubble.textContent = '📋 ' + part.text;
                } else {
                    bubble.className = 'bubble assistant';
                    bubble.textContent = part.text;
                }
                box.appendChild(bubble);
            }
        } else {
            const bubble = document.createElement('div');
            bubble.className = `bubble ${item.role}`;
            bubble.textContent = item.text;
            box.appendChild(bubble);
        }
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
            state.currentAssistantBubble = null;  // 清空当前助手气泡，让用户问题显示在最前面
            setStatus('listening');
            break;
        case 'transcript':
            appendTranscript(msg.role, msg.delta, !!msg.final);
            break;
        case 'board':
            appendBoard(msg.delta, !!msg.new_segment);
            break;
        case 'new_response':
            state.currentAssistantBubble = null;
            break;
        case 'state':
            setStatus(msg.value);
            break;
        case 'title':
            renameCurrentSession(msg.value);
            break;
        case 'context_usage':
            setContextUsage(msg.chars, msg.count);
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
    await promptMicPermission();
    openWebSocket();
    try {
        await AudioIO.startCapture((b64) => {
            if (state.talking) {
                sendWs({ type: 'audio', data: b64 });
            }
        });
    } catch (err) {
        showMicError(err);
        return;
    }
    state.talking = true;
    updateTalkButton();
    setStatus('listening');
    startLevelMeter();
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
    stopLevelMeter();
    clearBoard();
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
    clearBoard();
    state.sessionId = sessionId;
    const session = await api(`/api/sessions/${sessionId}`);
    state.currentSession = session;
    document.getElementById('session-title').textContent = session.title;
    document.getElementById('prompt-input').value = session.system_prompt;
    setOutputMode(session.output_mode);
    renderTranscriptHistory(session.transcript);
    updateContextUsage();
    renderSessions();
}

// ==========================================
// 上下文用量显示：字符数近似 token 数
// 两条来源：切换会话/打开设置时回读会话；对话中后端实时推送
// ==========================================
function setContextUsage(chars, count) {
    document.getElementById('context-usage').textContent =
        `上下文用量：约 ${chars} / ${CONTEXT_LIMIT} 字符（${count} 条）`;
}

function updateContextUsage() {
    const transcript = (state.currentSession && state.currentSession.transcript) || [];
    const used = transcript.reduce((sum, item) => sum + (item.text || '').length, 0);
    setContextUsage(used, transcript.length);
}

// ==========================================
// 回读当前会话并刷新字幕与用量（不打断进行中的对话）
// ==========================================
async function refreshCurrentSession() {
    if (!state.sessionId) {
        return;
    }
    state.currentSession = await api(`/api/sessions/${state.sessionId}`);
    renderTranscriptHistory(state.currentSession.transcript);
    updateContextUsage();
}

// ==========================================
// 压缩上下文：旧对话交给后端摘要，下次开始对话生效
// ==========================================
async function compressContext() {
    if (!state.sessionId) {
        toast('请先选择一个会话');
        return;
    }
    try {
        await api(`/api/sessions/${state.sessionId}/compress`, { method: 'POST' });
        toast('上下文已压缩，下次开始对话生效');
        await refreshCurrentSession();
    } catch (err) {
        toast(err.message, 6000);
    }
}

// ==========================================
// 清空历史：确认后清空本会话对话记录
// ==========================================
async function clearHistory() {
    if (!state.sessionId) {
        toast('请先选择一个会话');
        return;
    }
    if (!window.confirm('确定清空本会话的全部对话记录吗？')) {
        return;
    }
    await api(`/api/sessions/${state.sessionId}/clear_history`, { method: 'POST' });
    toast('历史已清空，下次开始对话生效');
    await refreshCurrentSession();
}

// ==========================================
// 打开设置面板：先回读会话刷新上下文用量
// ==========================================
async function openSettings() {
    if (state.sessionId) {
        try {
            await refreshCurrentSession();
        } catch (err) {
            // 回读失败不影响面板打开，用量显示保持旧值
        }
    }
    document.getElementById('settings-drawer').classList.remove('hidden');
}

async function deleteSession(sessionId) {
    await api(`/api/sessions/${sessionId}`, { method: 'DELETE' });
    if (state.sessionId === sessionId) {
        state.sessionId = null;
        document.getElementById('session-title').textContent = '未选择会话';
        document.getElementById('transcript').innerHTML = '';
        clearBoard();
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
    document.getElementById('settings-btn').addEventListener('click', openSettings);
    document.getElementById('compress-btn').addEventListener('click', compressContext);
    document.getElementById('clear-history-btn').addEventListener('click', clearHistory);
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
    document.getElementById('board-toggle-btn').addEventListener('click', () => {
        setBoardVisible(!state.boardOn);
    });
    document.getElementById('board-clear-btn').addEventListener('click', clearBoard);
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
        initBoard();
        if (state.sessions.length > 0) {
            await selectSession(state.sessions[0].id);
        }
    } catch (err) {
        toast(`初始化失败：${err.message}`);
    }
});
