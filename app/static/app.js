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
