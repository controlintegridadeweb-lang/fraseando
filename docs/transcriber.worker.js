/** A separate worker allows the UI to cancel an expensive model or inference. */
import { pipeline, env } from "https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2";

env.allowLocalModels = false;
env.useBrowserCache = true;
env.backends.onnx.wasm.wasmPaths = "https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2/dist/";
env.backends.onnx.wasm.numThreads = 1;
env.backends.onnx.wasm.proxy = false;

const MODELS = Object.freeze({
  tiny: "Xenova/whisper-tiny",
  base: "Xenova/whisper-base",
  small: "Xenova/whisper-small",
});
let transcriber = null;
let loadedModel = null;

self.onmessage = async ({ data }) => {
  const { id, type } = data;
  try {
    if (type === "load") {
      if (!Object.hasOwn(MODELS, data.model)) throw new Error("Modelo não suportado no navegador.");
      if (loadedModel !== data.model || !transcriber) {
        if (transcriber?.dispose) await transcriber.dispose();
        transcriber = null;
        loadedModel = null;
        transcriber = await pipeline("automatic-speech-recognition", MODELS[data.model], {
          progress_callback: (info) => self.postMessage({ id, type: "progress", info }),
        });
        loadedModel = data.model;
      }
      self.postMessage({ id, type: "result", value: true });
    } else if (type === "transcribe") {
      if (!transcriber) throw new Error("Carregue um modelo antes de transcrever.");
      const saida = await transcriber(data.samples, {
        language: "portuguese",
        task: "transcribe",
        return_timestamps: true,
        chunk_length_s: 20,
        stride_length_s: 3,
      });
      self.postMessage({ id, type: "result", value: {
        texto: (saida.text || "").trim(),
        trechos: (saida.chunks || []).map((chunk) => ({
          text: String(chunk.text || ""),
          start: Array.isArray(chunk.timestamp) && Number.isFinite(chunk.timestamp[0]) ? chunk.timestamp[0] : 0,
          end: Array.isArray(chunk.timestamp) && Number.isFinite(chunk.timestamp[1]) ? chunk.timestamp[1] : null,
        })),
      } });
    } else {
      throw new Error("Operação desconhecida no motor de transcrição.");
    }
  } catch (error) {
    self.postMessage({ id, type: "error", message: error?.message || String(error) });
  }
};
