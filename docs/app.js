import { SAMPLE_RATE, MAX_MINUTOS_NAVEGADOR, validarArquivo, fingerprintArquivo,
  planoDePartes, resumivel, toSrt, toVtt } from "./transcription-utils.mjs";
import { BrowserWhisperWorker } from "./worker-client.mjs";

const DB_NAME = "fraseando";
const STORE = "trabalho";
const JOB_KEY = "atual";
const LIMITE_DECODE_BYTES = 8 * 1024 * 1024;
const FFMPEG_CORE = "https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.6/dist/esm";

const els = {
  file: document.getElementById("arquivo"),
  preview: document.getElementById("preview"),
  model: document.getElementById("modelo"),
  split: document.getElementById("dividir"),
  minutes: document.getElementById("minutos"),
  start: document.getElementById("iniciar"),
  cancel: document.getElementById("cancelar"),
  status: document.getElementById("status"),
  bar: document.getElementById("barra"),
  result: document.getElementById("resultado"),
  editor: document.getElementById("editor"),
  original: document.getElementById("original"),
  trechos: document.getElementById("trechos"),
  txt: document.getElementById("baixar-txt"),
  md: document.getElementById("baixar-md"),
  srt: document.getElementById("baixar-srt"),
  vtt: document.getElementById("baixar-vtt"),
  retomada: document.getElementById("retomada"),
  retomadaTexto: document.getElementById("retomada-texto"),
  continuar: document.getElementById("continuar"),
  descartar: document.getElementById("descartar"),
};

const whisper = new BrowserWhisperWorker();
let activeRun = null;
let fingerprintAtual = null;
let chunks = [];
let objectUrl = null;
let pcmCache = null;
let arquivoAtual = null;
let ocupado = false;
let ffmpeg = null;
let ffmpegPronto = false;
let ffmpegLogs = [];

function detalheErro(erro) {
  return (erro && (erro.message || String(erro))) || "erro desconhecido";
}

function setStatus(text) {
  els.status.textContent = text;
}

function setProgress(value) {
  els.bar.hidden = false;
  els.bar.value = Math.min(1, Math.max(0, value));
}

function abrirDb() {
  return new Promise((resolve, reject) => {
    if (!globalThis.indexedDB) return reject(new Error("Armazenamento local indisponível."));
    const pedido = indexedDB.open(DB_NAME, 1);
    pedido.onupgradeneeded = () => {
      if (!pedido.result.objectStoreNames.contains(STORE)) pedido.result.createObjectStore(STORE);
    };
    pedido.onsuccess = () => resolve(pedido.result);
    pedido.onerror = () => reject(pedido.error || new Error("Falha no armazenamento local."));
  });
}

async function trabalhoDb(mode, operation) {
  const db = await abrirDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    const store = tx.objectStore(STORE);
    let value = null;
    const req = operation(store);
    req.onsuccess = () => { value = req.result; };
    tx.oncomplete = () => { db.close(); resolve(value); };
    tx.onabort = () => { db.close(); reject(tx.error || new Error("Armazenamento cancelado.")); };
    tx.onerror = () => { /* onabort reports the error once */ };
  });
}

async function lerTrabalho() {
  try { return (await trabalhoDb("readonly", (store) => store.get(JOB_KEY))) || null; }
  catch (error) { console.warn("Retomada indisponível:", error); return null; }
}

async function salvarProgresso(job) {
  try {
    await trabalhoDb("readwrite", (store) => store.put({ ...job, atualizado: Date.now() }, JOB_KEY));
    return true;
  } catch (error) {
    console.warn("Não foi possível guardar o progresso; exporte o texto parcial quando necessário.", error);
    setStatus("Aviso: não foi possível guardar o progresso local. Evite fechar esta aba.");
    return false;
  }
}

async function apagarTrabalho() {
  try {
    await trabalhoDb("readwrite", (store) => store.delete(JOB_KEY));
    return true;
  } catch (error) {
    console.warn("Não foi possível apagar o progresso local:", error);
    return false;
  }
}

function soltarPreview(limparCampo = false) {
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }
  els.preview.removeAttribute("src");
  els.preview.hidden = true;
  if (limparCampo) {
    els.file.value = "";
    arquivoAtual = null;
  }
}

function baixar(nome, conteudo, tipo) {
  const blob = new Blob([conteudo], { type: tipo });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = nome;
  document.body.appendChild(link);
  link.click();
  setTimeout(() => { link.remove(); URL.revokeObjectURL(url); }, 1000);
}

function minutosDaUi(job) {
  const pedido = job ? job.minutos : Number(els.minutes.value);
  if (!Number.isInteger(pedido) || pedido < 1 || pedido > MAX_MINUTOS_NAVEGADOR) {
    throw new Error("Escolha entre 1 e 8 minutos por parte.");
  }
  return pedido;
}

function mostrarResultado(texto, trechos) {
  chunks = trechos;
  els.original.value = texto;
  els.editor.value = texto;
  els.trechos.textContent = trechos.length
    ? trechos.map((part) => `${(part.start / 60).toFixed(2)}–${(part.end / 60).toFixed(2)} min · ${part.text}`).join("\n")
    : "Nenhum trecho com tempo foi devolvido por este modelo.";
  els.result.hidden = false;
}

function progressoModelo(info) {
  if (!info) return;
  if (info.status === "progress") {
    const pct = Number(info.progress) || 0;
    setStatus(`Baixando o modelo (${info.file || "Whisper"}): ${pct.toFixed(0)}%`);
    setProgress(Math.min(0.28, pct / 100 * 0.28));
  } else if (info.status === "download" || info.status === "initiate") {
    setStatus(`Preparando ${info.file || "o modelo Whisper"}…`);
  }
}

async function carregarModelo(nome) {
  setStatus("Preparando o modelo Whisper no navegador; o primeiro download pode demorar.");
  await whisper.load(nome, progressoModelo);
}

async function para16k(buffer) {
  const duracao = Number(buffer.duration) || (buffer.length / buffer.sampleRate);
  const amostras = Math.max(1, Math.round(duracao * SAMPLE_RATE));
  const offline = new OfflineAudioContext(1, amostras, SAMPLE_RATE);
  const origem = offline.createBufferSource();
  origem.buffer = buffer;
  origem.connect(offline.destination);
  origem.start(0);
  const renderizado = await offline.startRendering();
  return new Float32Array(renderizado.getChannelData(0));
}

async function decodificarArquivo(file) {
  if (pcmCache && pcmCache.file === file) return pcmCache.data;
  const contexto = new AudioContext();
  try {
    if (contexto.state === "suspended") await contexto.resume();
    const decoded = await contexto.decodeAudioData(await file.arrayBuffer());
    const data = await para16k(decoded);
    pcmCache = { file, data };
    return data;
  } finally {
    await contexto.close();
  }
}

function fatiarPcm(data, inicio, duracao) {
  const i0 = Math.max(0, Math.floor(inicio * SAMPLE_RATE));
  const i1 = duracao
    ? Math.min(data.length, Math.floor((inicio + duracao) * SAMPLE_RATE))
    : data.length;
  return new Float32Array(data.subarray(i0, Math.max(i0 + 1, i1)));
}

function trechosDaSaida(saida, deslocamento = 0, duracaoDaParte = 0) {
  return (saida.trechos || []).map((chunk) => {
    const start = Number.isFinite(chunk.start) ? Math.max(0, chunk.start) : 0;
    const end = Number.isFinite(chunk.end) ? Math.max(start, chunk.end) : Math.max(start, duracaoDaParte);
    return { text: chunk.text || "", start: start + deslocamento, end: end + deslocamento };
  });
}

async function reconhecer(entrada, deslocamento = 0, duracaoDaParte = 0) {
  const saida = await whisper.recognize(entrada);
  return {
    texto: saida.texto,
    trechos: trechosDaSaida(saida, deslocamento, duracaoDaParte),
  };
}

function nomeEntrada(file) {
  return String(file.name || "").toLowerCase().endsWith(".mp4") ? "entrada.mp4" : "entrada.mp3";
}

async function lerDuracao(file) {
  if (arquivoAtual === file && Number.isFinite(els.preview.duration) && els.preview.duration > 0) {
    return els.preview.duration;
  }
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const audio = document.createElement("audio");
    const signal = activeRun?.controller.signal;
    let settled = false;
    let timeout;
    const terminar = (valor) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      signal?.removeEventListener("abort", cancelar);
      audio.onloadedmetadata = null;
      audio.onerror = null;
      audio.removeAttribute("src");
      URL.revokeObjectURL(url);
      resolve(valor);
    };
    const cancelar = () => terminar(0);
    if (signal?.aborted) { terminar(0); return; }
    signal?.addEventListener("abort", cancelar, { once: true });
    timeout = setTimeout(() => terminar(0), 12000);
    audio.preload = "metadata";
    audio.onloadedmetadata = () => terminar(Number.isFinite(audio.duration) ? audio.duration : 0);
    audio.onerror = () => terminar(0);
    audio.src = url;
  });
}

async function urlComoBlob(url, tipo) {
  const resposta = await fetch(url, { signal: activeRun?.controller.signal });
  if (!resposta.ok) throw new Error(`Não foi possível carregar o componente de áudio: HTTP ${resposta.status}`);
  return URL.createObjectURL(new Blob([await resposta.blob()], { type: tipo }));
}

function resumoLogs() {
  const linhas = ffmpegLogs.filter(Boolean).slice(-8);
  return linhas.length ? linhas.join(" | ") : "";
}

async function carregarFfmpeg() {
  if (ffmpegPronto) return ffmpeg;
  setStatus("Preparando o recorte de áudio (primeira execução requer download)…");
  const { FFmpeg } = await import(new URL("./ffmpeg/index.js", import.meta.url).href);
  const motor = new FFmpeg();
  ffmpeg = motor;
  ffmpegLogs = [];
  motor.on("log", ({ message }) => {
    if (message) {
      ffmpegLogs.push(message);
      if (ffmpegLogs.length > 50) ffmpegLogs.shift();
    }
  });
  motor.on("progress", ({ progress }) => {
    if (Number.isFinite(progress) && progress > 0) setProgress(0.3 + Math.min(0.08, progress * 0.08));
  });
  let coreUrl = null;
  let wasmUrl = null;
  try {
    coreUrl = await urlComoBlob(`${FFMPEG_CORE}/ffmpeg-core.js`, "text/javascript");
    wasmUrl = await urlComoBlob(`${FFMPEG_CORE}/ffmpeg-core.wasm`, "application/wasm");
    if (activeRun?.cancelled) throw new Error("Transcrição cancelada.");
    await motor.load({
      classWorkerURL: new URL("./ffmpeg/worker.js", import.meta.url).href,
      coreURL: coreUrl,
      wasmURL: wasmUrl,
    });
    if (activeRun?.cancelled) throw new Error("Transcrição cancelada.");
    ffmpegPronto = true;
    return motor;
  } catch (error) {
    motor.terminate();
    if (ffmpeg === motor) ffmpeg = null;
    ffmpegPronto = false;
    throw error;
  } finally {
    if (coreUrl) URL.revokeObjectURL(coreUrl);
    if (wasmUrl) URL.revokeObjectURL(wasmUrl);
  }
}

async function duracaoViaFfmpeg(motor, inputPath) {
  let duracao = 0;
  const ler = ({ message }) => {
    const achado = /Duration: (\d+):(\d+):(\d+(?:\.\d+)?)/.exec(message || "");
    if (achado) duracao = Number(achado[1]) * 3600 + Number(achado[2]) * 60 + Number(achado[3]);
  };
  motor.on("log", ler);
  try {
    await motor.exec(["-hide_banner", "-i", inputPath]);
  } finally {
    motor.off("log", ler);
  }
  return duracao;
}

async function prepararEntrada(motor, file) {
  const origem = nomeEntrada(file);
  try {
    try {
      await motor.createDir("/in");
    } catch {
      // diretório já existe
    }
    const nomeado = new File([file], origem, { type: file.type || "application/octet-stream" });
    await motor.mount("WORKERFS", { files: [nomeado] }, "/in");
    return { inputPath: `/in/${origem}`, mounted: true, origem };
  } catch (erroMontagem) {
    if (file.size > 64 * 1024 * 1024) {
      throw new Error("O navegador não conseguiu montar o arquivo grande sem duplicá-lo na memória. Use a versão local em Python.");
    }
    console.warn("WORKERFS indisponível; copiando arquivo menor.", erroMontagem);
    const dados = new Uint8Array(await file.arrayBuffer());
    const copia = new Uint8Array(dados);
    await motor.writeFile(origem, copia);
    const itens = await motor.listDir("/");
    const nomes = (itens || []).map((item) => item.name);
    if (!nomes.includes(origem)) {
      throw new Error(`O arquivo não entrou no recorte. ${resumoLogs() || detalheErro(erroMontagem)}`);
    }
    return { inputPath: origem, mounted: false, origem };
  }
}

async function wavParaPcm(bytes) {
  const contexto = new AudioContext();
  try {
    if (contexto.state === "suspended") await contexto.resume();
    const copia = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    const decoded = await contexto.decodeAudioData(copia);
    return para16k(decoded);
  } finally {
    await contexto.close();
  }
}

async function executarCorte(motor, args) {
  ffmpegLogs = [];
  try {
    const codigo = await motor.exec(args);
    if (codigo !== 0 && codigo !== undefined) {
      throw new Error(`FFmpeg saiu com código ${codigo}`);
    }
  } catch (erro) {
    const extra = resumoLogs();
    throw new Error(extra ? `${detalheErro(erro)} · ${extra}` : detalheErro(erro));
  }
}

async function recortarPcm(motor, inputPath, inicio, duracao) {
  const saida = "parte.wav";
  try {
    await motor.deleteFile(saida);
  } catch {
    // arquivo ainda não existia
  }
  const t = String(Math.max(0.2, duracao));
  const ss = String(Math.max(0, inicio));
  const comum = ["-vn", "-ac", "1", "-ar", String(SAMPLE_RATE), "-c:a", "pcm_s16le", saida];
  try {
    await executarCorte(motor, ["-ss", ss, "-t", t, "-i", inputPath, ...comum]);
  } catch (erro) {
    if (!String(detalheErro(erro)).includes("Code=8")) throw erro;
    await executarCorte(motor, ["-i", inputPath, "-ss", ss, "-t", t, ...comum]);
  }
  const bruto = await motor.readFile(saida);
  try {
    await motor.deleteFile(saida);
  } catch {
    // segue com a cópia já lida
  }
  if (!bruto || bruto.byteLength < 44) throw new Error(`A parte recortada veio vazia. ${resumoLogs()}`);
  return wavParaPcm(bruto);
}

async function mostrarRetomada() {
  const job = await lerTrabalho();
  if (!job || job.status === "concluido") {
    els.retomada.hidden = true;
    return null;
  }
  els.retomada.hidden = false;
  const index = Number.isInteger(job.nextIndex) ? job.nextIndex : 0;
  els.retomadaTexto.textContent = `${job.fileName} · ${index} de ${job.partes} partes concluídas. Selecione novamente o mesmo arquivo para continuar.`;
  els.continuar.disabled = ocupado || !arquivoAtual || !fingerprintAtual ||
    !resumivel(job, arquivoAtual, fingerprintAtual);
  return job;
}

function novoJob(file, { modelo, dividir, minutos, duracao, plano, fingerprint }) {
  return {
    fileName: file.name,
    fileSize: file.size,
    lastModified: file.lastModified,
    fingerprint,
    modelo, dividir, minutos, duracao, plano,
    partes: plano.length, nextIndex: 0, textos: [], trechos: [], status: "andamento",
  };
}

function verificarCancelamento(run) {
  if (run.cancelled) throw new Error("Transcrição cancelada.");
}

function atualizarOcupado(value) {
  ocupado = value;
  els.start.disabled = value || !arquivoAtual;
  els.cancel.disabled = !value;
  els.cancel.hidden = !value;
  els.continuar.disabled = value;
  els.file.disabled = value;
  els.model.disabled = value;
  els.split.disabled = value;
  els.minutes.disabled = value || !els.split.checked;
}

async function transcreverPartes(job, obterPcm, run) {
  for (let i = job.nextIndex; i < job.partes; i += 1) {
    verificarCancelamento(run);
    const parte = job.plano[i];
    setStatus(`Reconhecendo a parte ${i + 1} de ${job.partes} (${(parte.duration / 60).toFixed(1)} min)…`);
    setProgress(0.38 + (0.58 * (i / job.partes)));
    const fatia = await obterPcm(parte);
    verificarCancelamento(run);
    const resultado = await reconhecer(fatia, parte.start, parte.duration);
    verificarCancelamento(run);
    job.textos.push(resultado.texto);
    job.trechos.push(...resultado.trechos);
    job.nextIndex = i + 1;
    run.persisted = await salvarProgresso(job);
    // Permit event handlers to repaint between parts.
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

async function transcreverArquivo(file, { retomar = false } = {}) {
  if (ocupado) return;
  try { validarArquivo(file); }
  catch (error) { setStatus(error.message); return; }
  const run = { cancelled: false, persisted: false, controller: new AbortController() };
  activeRun = run;
  atualizarOcupado(true);
  setProgress(0.03);
  let job = null;
  let motor = null;
  let entrada = null;
  try {
    const fingerprint = fingerprintAtual || await fingerprintArquivo(file);
    job = retomar ? await lerTrabalho() : null;
    if (retomar && !resumivel(job, file, fingerprint)) {
      throw new Error("Arquivo diferente ou progresso inválido. Selecione a gravação original ou inicie uma nova transcrição.");
    }
    if (!retomar) await apagarTrabalho();
    verificarCancelamento(run);
    const modelo = job?.modelo || els.model.value;
    await carregarModelo(modelo);
    verificarCancelamento(run);
    setStatus("Medindo a duração da gravação…");
    let duracao = job?.duracao || await lerDuracao(file);
    verificarCancelamento(run);
    const minutos = minutosDaUi(job);
    const maxSeg = minutos * 60;
    // An unknown duration is never decoded whole: first inspect it through FFmpeg.
    const arquivoGrande = !duracao || file.size > LIMITE_DECODE_BYTES || duracao > maxSeg || duracao > 12 * 60;
    const dividir = arquivoGrande || (job ? job.dividir : els.split.checked);

    if (arquivoGrande) {
      setStatus("Arquivo grande: recortando partes sem decodificar o PCM completo…");
      motor = await carregarFfmpeg();
      verificarCancelamento(run);
      entrada = await prepararEntrada(motor, file);
      verificarCancelamento(run);
      if (!duracao) duracao = await duracaoViaFfmpeg(motor, entrada.inputPath);
      verificarCancelamento(run);
      if (!duracao) throw new Error(`Não foi possível medir a duração. ${resumoLogs()}`);
      if (!job) {
        job = novoJob(file, { modelo, dividir: true, minutos, duracao,
          plano: planoDePartes(duracao, true, minutos), fingerprint });
      }
      job.status = "andamento";
      run.persisted = await salvarProgresso(job);
      await transcreverPartes(job, (parte) => recortarPcm(motor, entrada.inputPath, parte.start, parte.duration), run);
    } else {
      setStatus("Decodificando o áudio neste navegador…");
      setProgress(0.34);
      const pcm = await decodificarArquivo(file);
      verificarCancelamento(run);
      duracao = pcm.length / SAMPLE_RATE;
      if (!job) {
        job = novoJob(file, { modelo, dividir, minutos, duracao,
          plano: planoDePartes(duracao, dividir, minutos), fingerprint });
      }
      job.status = "andamento";
      run.persisted = await salvarProgresso(job);
      await transcreverPartes(job, async (parte) => fatiarPcm(pcm, parte.start, parte.duration), run);
    }

    verificarCancelamento(run);
    mostrarResultado(job.textos.filter(Boolean).join(" ").trim(), job.trechos);
    const apagado = await apagarTrabalho();
    els.retomada.hidden = true;
    setProgress(1);
    setStatus(apagado
      ? "Concluído. O áudio foi processado no navegador e não foi enviado ao servidor."
      : "Transcrição concluída, mas não foi possível limpar o progresso armazenado. Verifique os dados deste site no navegador.");
    soltarPreview(true);
    fingerprintAtual = null;
  } catch (error) {
    if (run.cancelled) {
      if (job) {
        job.status = "pausado";
        run.persisted = await salvarProgresso(job);
        if (job.nextIndex > 0) mostrarResultado(job.textos.filter(Boolean).join(" ").trim(), job.trechos);
      }
      setStatus(job && run.persisted
        ? `Cancelado. ${job.nextIndex} de ${job.partes} partes preservadas neste aparelho.`
        : job ? "Cancelado. O texto parcial pode ser baixado, mas a retomada não foi salva neste aparelho."
          : "Cancelado antes da primeira parte; nenhum texto foi gerado.");
    } else {
      console.error(error);
      setStatus(`Não foi possível transcrever: ${detalheErro(error)}`);
    }
  } finally {
    pcmCache = null;
    // Free the model's WASM allocations after each job, not only after cancellation.
    whisper.terminate();
    if (entrada && motor && ffmpegPronto) {
      try {
        if (entrada.mounted) await motor.unmount("/in");
        else await motor.deleteFile(entrada.origem);
      } catch (error) { console.warn("Não foi possível desmontar o arquivo temporário:", error); }
    }
    // ffmpeg.wasm owns a second WASM memory and file-system; release it after every job.
    motor?.terminate();
    if (ffmpeg && !motor) ffmpeg.terminate();
    ffmpeg = null;
    ffmpegPronto = false;
    atualizarOcupado(false);
    activeRun = null;
    await mostrarRetomada();
  }
}

els.split.addEventListener("change", () => {
  els.minutes.disabled = !els.split.checked || ocupado;
});

els.file.addEventListener("change", async () => {
  soltarPreview(false);
  pcmCache = null;
  fingerprintAtual = null;
  const file = els.file.files[0];
  arquivoAtual = file || null;
  els.start.disabled = true;
  els.result.hidden = true;
  if (!file) { await mostrarRetomada(); return; }
  try {
    validarArquivo(file);
    const fingerprint = await fingerprintArquivo(file);
    if (arquivoAtual !== file) return;
    fingerprintAtual = fingerprint;
    els.start.disabled = ocupado;
  } catch (error) {
    setStatus(detalheErro(error));
    els.start.disabled = true;
    return;
  }
  objectUrl = URL.createObjectURL(file);
  els.preview.src = objectUrl;
  els.preview.hidden = false;
  const mb = file.size / 1048576;
  setStatus(mb > 8
    ? `${file.name} · ${mb.toFixed(1)} MB. Será recortado em partes no navegador.`
    : `${file.name} · ${mb.toFixed(1)} MB. Pronto para transcrever.`);
  await mostrarRetomada();
});

els.start.addEventListener("click", async () => {
  const file = arquivoAtual || els.file.files[0];
  if (!file) return;
  await transcreverArquivo(file);
});

els.cancel.addEventListener("click", () => {
  if (!activeRun || activeRun.cancelled) return;
  activeRun.cancelled = true;
  els.cancel.disabled = true;
  setStatus("Cancelando e preservando as partes já concluídas…");
  activeRun.controller.abort();
  whisper.terminate();
  // Terminates any in-flight FFmpeg operation; mounted files are lost with its worker.
  ffmpeg?.terminate();
  ffmpeg = null;
  ffmpegPronto = false;
});

els.continuar.addEventListener("click", async () => {
  const job = await lerTrabalho();
  if (!job) return;
  const file = arquivoAtual || els.file.files[0];
  if (!file || !resumivel(job, file, fingerprintAtual)) {
    setStatus("Escolha a mesma gravação original para continuar; o áudio não fica armazenado.");
    return;
  }
  await transcreverArquivo(file, { retomar: true });
});

els.descartar.addEventListener("click", async () => {
  if (await apagarTrabalho()) {
    els.retomada.hidden = true;
    setStatus("Progresso local apagado.");
  } else {
    setStatus("Falha ao apagar o progresso. Limpe os dados deste site nas configurações do navegador.");
  }
});

window.addEventListener("pagehide", () => {
  if (objectUrl) URL.revokeObjectURL(objectUrl);
});

els.txt.addEventListener("click", () => baixar("transcricao.txt", els.editor.value, "text/plain;charset=utf-8"));
els.md.addEventListener("click", () => baixar("transcricao.md", `# Transcrição\n\n${els.editor.value}`, "text/markdown;charset=utf-8"));
els.srt.addEventListener("click", () => baixar("transcricao.srt", toSrt(chunks), "text/plain;charset=utf-8"));
els.vtt.addEventListener("click", () => baixar("transcricao.vtt", toVtt(chunks), "text/vtt;charset=utf-8"));

mostrarRetomada().catch((error) => console.warn("Retomada indisponível:", error));
