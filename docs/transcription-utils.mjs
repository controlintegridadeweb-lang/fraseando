/** Pure helpers shared by the browser UI and its offline test suite. */
export const SAMPLE_RATE = 16000;
export const MAX_MINUTOS_NAVEGADOR = 8;
export const MAX_FILE_BYTES = 512 * 1024 * 1024;

export function formatTime(seconds, separator = ",") {
  if (!Number.isFinite(Number(seconds)) || Number(seconds) < 0) {
    throw new RangeError("Timestamp inválido.");
  }
  const total = Math.round(Number(seconds) * 1000);
  if (!Number.isSafeInteger(total)) throw new RangeError("Timestamp fora do limite.");
  const h = Math.floor(total / 3600000);
  const m = Math.floor((total % 3600000) / 60000);
  const s = Math.floor((total % 60000) / 1000);
  const ms = total % 1000;
  const pad = (n, size = 2) => String(n).padStart(size, "0");
  return `${pad(h)}:${pad(m)}:${pad(s)}${separator}${pad(ms, 3)}`;
}

export function subtitles(parts, kind = "srt") {
  if (!["srt", "vtt"].includes(kind)) throw new RangeError("Formato de legenda inválido.");
  const separator = kind === "vtt" ? "." : ",";
  const blocks = [];
  for (const part of parts) {
    const text = String(part.text ?? "").trim();
    if (!text) continue;
    if (Number(part.end) < Number(part.start)) throw new RangeError("Fim de trecho anterior ao início.");
    const timing = `${formatTime(part.start, separator)} --> ${formatTime(part.end, separator)}`;
    blocks.push(`${blocks.length + 1}\n${timing}\n${text}`);
  }
  const content = blocks.join("\n\n");
  return (kind === "vtt" ? "WEBVTT\n\n" : "") + content + (content ? "\n" : "");
}

export function toSrt(parts) { return subtitles(parts, "srt"); }
export function toVtt(parts) { return subtitles(parts, "vtt"); }

export function planoDePartes(duracao, dividir, minutos) {
  const total = Number(duracao);
  const limit = Number(minutos);
  if (!Number.isFinite(total) || total <= 0) throw new RangeError("Duração inválida.");
  if (!Number.isFinite(limit) || limit < 1 || limit > MAX_MINUTOS_NAVEGADOR) {
    throw new RangeError("O tamanho da parte deve estar entre 1 e 8 minutos.");
  }
  const max = limit * 60;
  if (!dividir && total > max) {
    throw new RangeError("Áudio longo: ative a divisão em partes.");
  }
  if (total <= max) return [{ start: 0, duration: total }];
  const partes = [];
  for (let start = 0; start < total; start += max) {
    partes.push({ start, duration: Math.min(max, total - start) });
  }
  return partes;
}

export function validarArquivo(file) {
  if (!file) throw new Error("Selecione um arquivo MP3 ou MP4.");
  const name = String(file.name || "");
  if (!/\.(mp3|mp4)$/i.test(name)) throw new Error("Formato não permitido: selecione MP3 ou MP4.");
  if (!Number.isFinite(file.size) || file.size <= 0) throw new Error("O arquivo está vazio ou é inválido.");
  if (file.size > MAX_FILE_BYTES) {
    throw new Error("O navegador aceita até 512 MB. Para arquivos maiores, use a versão local em Python.");
  }
}

// Metadados isoladamente não garantem que um arquivo de retomada é o mesmo.
// Uma impressão SHA-256 das pontas detecta alterações comuns sem carregar o MP3/MP4 inteiro.
export async function fingerprintArquivo(file, subtle = globalThis.crypto?.subtle) {
  validarArquivo(file);
  if (!subtle) throw new Error("Para retomar com segurança, abra a página via HTTPS ou localhost.");
  const block = 64 * 1024;
  const first = await file.slice(0, block).arrayBuffer();
  const last = await file.slice(Math.max(0, file.size - block)).arrayBuffer();
  const meta = new TextEncoder().encode(`${file.name}|${file.size}|${file.lastModified}|`);
  const bytes = new Uint8Array(meta.length + first.byteLength + last.byteLength);
  bytes.set(meta);
  bytes.set(new Uint8Array(first), meta.length);
  bytes.set(new Uint8Array(last), meta.length + first.byteLength);
  const hash = await subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(hash)].map((x) => x.toString(16).padStart(2, "0")).join("");
}

export function resumivel(job, file, fingerprint) {
  return !!job && job.status !== "concluido" && job.fileName === file.name &&
    job.fileSize === file.size && job.lastModified === file.lastModified &&
    typeof job.fingerprint === "string" && job.fingerprint === fingerprint &&
    Number.isInteger(job.nextIndex) && job.nextIndex >= 0 &&
    Array.isArray(job.plano) && job.nextIndex <= job.plano.length &&
    Array.isArray(job.textos) && job.textos.length === job.nextIndex &&
    Array.isArray(job.trechos);
}
