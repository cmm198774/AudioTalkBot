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
