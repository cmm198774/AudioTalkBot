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
        // 分析节点：实时读取输入电平，供界面显示麦克风是否真的采到声音
        this.analyser = this.audioCtx.createAnalyser();
        this.analyser.fftSize = 512;
        // 经零增益节点挂到输出，保证 worklet 被调度但不发声
        const silent = this.audioCtx.createGain();
        silent.gain.value = 0;
        source.connect(this.workletNode);
        source.connect(this.analyser);
        this.workletNode.connect(silent);
        silent.connect(this.audioCtx.destination);
    },

    // ==========================================
    // 读取当前麦克风输入电平（RMS，0~1）
    // ==========================================
    getInputLevel() {
        if (!this.analyser) {
            return 0;
        }
        const data = new Uint8Array(this.analyser.fftSize);
        this.analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) {
            const v = (data[i] - 128) / 128;
            sum += v * v;
        }
        return Math.sqrt(sum / data.length);
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
        if (this.analyser) {
            this.analyser.disconnect();
            this.analyser = null;
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
