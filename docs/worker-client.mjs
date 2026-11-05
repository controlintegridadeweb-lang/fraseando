/** Keeps CPU-intensive Whisper inference off the UI thread; termination is immediate. */
export class BrowserWhisperWorker {
  constructor(workerFactory = () => new Worker(new URL("./transcriber.worker.js", import.meta.url), { type: "module" })) {
    this.workerFactory = workerFactory;
    this.worker = null;
    this.pending = new Map();
    this.nextId = 0;
    this.loadedModel = null;
  }

  ensureWorker() {
    if (this.worker) return this.worker;
    const worker = this.workerFactory();
    worker.onmessage = ({ data }) => {
      if (data.type === "progress") {
        this.pending.get(data.id)?.onProgress?.(data.info);
        return;
      }
      const pending = this.pending.get(data.id);
      if (!pending) return;
      this.pending.delete(data.id);
      if (data.type === "error") pending.reject(new Error(data.message || "Falha no reconhecimento."));
      else if (data.type === "result") pending.resolve(data.value);
    };
    worker.onerror = (event) => {
      event.preventDefault?.();
      this.terminate(new Error("Falha ao carregar o motor de transcrição. Confira a rede, o modelo e a memória."));
    };
    worker.onmessageerror = () => this.terminate(new Error("Não foi possível transferir o áudio ao motor de transcrição."));
    this.worker = worker;
    return worker;
  }

  request(type, data, transfer = [], onProgress) {
    const worker = this.ensureWorker();
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject, onProgress });
      try {
        worker.postMessage({ id, type, ...data }, transfer);
      } catch (error) {
        this.pending.delete(id);
        reject(error);
      }
    });
  }

  async load(model, onProgress) {
    if (this.loadedModel === model && this.worker) return;
    await this.request("load", { model }, [], onProgress);
    this.loadedModel = model;
  }

  async recognize(samples) {
    if (!(samples instanceof Float32Array) || !samples.length) {
      throw new Error("A parte de áudio está vazia.");
    }
    // Transfer rather than duplicate up to eight minutes of raw audio.
    return this.request("transcribe", { samples }, [samples.buffer]);
  }

  terminate(reason = new Error("Transcrição cancelada.")) {
    this.worker?.terminate();
    this.worker = null;
    this.loadedModel = null;
    for (const { reject } of this.pending.values()) reject(reason);
    this.pending.clear();
  }
}
