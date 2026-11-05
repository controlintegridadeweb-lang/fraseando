import test from "node:test";
import assert from "node:assert/strict";
import { File } from "node:buffer";
import { webcrypto } from "node:crypto";
import { formatTime, toSrt, toVtt, planoDePartes, validarArquivo,
  fingerprintArquivo, resumivel } from "../docs/transcription-utils.mjs";
import { BrowserWhisperWorker } from "../docs/worker-client.mjs";

test("legendas retêm milissegundos e carregam arredondamento", () => {
  assert.equal(formatTime(1.23456), "00:00:01,235");
  assert.equal(formatTime(59.9999), "00:01:00,000");
  assert.equal(formatTime(3600.001), "01:00:00,001");
  const parts = [{ start: 59.9999, end: 3600.001, text: " Fala. " }];
  assert.match(toSrt(parts), /00:01:00,000 --> 01:00:00,001/);
  assert.match(toVtt(parts), /^WEBVTT\n\n1\n00:01:00\.000 --> 01:00:00\.001/);
  assert.equal(toSrt([]), "");
  assert.equal(toVtt([]), "WEBVTT\n\n");
});

test("legendas rejeitam valores e pulam textos vazios", () => {
  assert.throws(() => formatTime(-1), /inválido/);
  assert.throws(() => formatTime(Number.NaN), /inválido/);
  assert.throws(() => toSrt([{ start: 2, end: 1, text: "erro" }]), /anterior/);
  assert.equal(toSrt([{ start: 0, end: 1, text: "" }, { start: 1, end: 2, text: "fala" }]).startsWith("1\n"), true);
});

test("plano divide 1 hora sem superar o máximo de 8 minutos", () => {
  const parts = planoDePartes(3600, true, 8);
  assert.equal(parts.length, 8);
  assert.equal(parts[0].start, 0);
  assert.equal(parts.at(-1).duration, 240);
  assert.equal(parts.reduce((n, part) => n + part.duration, 0), 3600);
  assert.ok(parts.every((part) => part.duration <= 480));
  assert.throws(() => planoDePartes(3600, false, 8), /divisão/);
  assert.throws(() => planoDePartes(60, true, 9), /entre 1 e 8/);
});

test("validação impede formatos, vazios e arquivos excessivos", () => {
  const file = new File(["a"], "f.mp3");
  assert.doesNotThrow(() => validarArquivo(file));
  assert.throws(() => validarArquivo(new File([], "f.mp3")), /vazio/);
  assert.throws(() => validarArquivo(new File(["a"], "f.exe")), /Formato/);
  assert.throws(() => validarArquivo({ name: "x.mp4", size: 512 * 1024 * 1024 + 1 }), /512 MB/);
});

test("retomada exige impressão de conteúdo, além dos metadados", async () => {
  const a = new File(["conteudo 1"], "reuniao.mp3", { lastModified: 123 });
  const b = new File(["conteudo 2"], "reuniao.mp3", { lastModified: 123 });
  const hashA = await fingerprintArquivo(a, webcrypto.subtle);
  const hashB = await fingerprintArquivo(b, webcrypto.subtle);
  assert.notEqual(hashA, hashB);
  const job = { fileName: a.name, fileSize: a.size, lastModified: a.lastModified,
    fingerprint: hashA, plano: [{ start: 0, duration: 1 }],
    nextIndex: 0, textos: [], trechos: [], status: "pausado" };
  assert.equal(resumivel(job, a, hashA), true);
  assert.equal(resumivel(job, b, hashB), false);
  assert.equal(resumivel({ ...job, textos: ["duplicado"] }, a, hashA), false);
});

class FakeWorker {
  constructor() { this.calls = []; this.terminated = false; }
  postMessage(data, transfer) { this.calls.push({ data, transfer }); }
  terminate() { this.terminated = true; }
  respond(index, value) {
    const { data } = this.calls[index];
    this.onmessage({ data: { id: data.id, type: "result", value } });
  }
}

test("worker carrega modelo uma vez, transfere áudio sem copiar e retorna resposta", async () => {
  const fake = new FakeWorker();
  const client = new BrowserWhisperWorker(() => fake);
  const loading = client.load("tiny");
  assert.equal(fake.calls.length, 1);
  fake.respond(0, true);
  await loading;
  await client.load("tiny");
  assert.equal(fake.calls.length, 1);
  const samples = new Float32Array([1, 2, 3]);
  const transcribing = client.recognize(samples);
  assert.equal(fake.calls[1].transfer[0], samples.buffer);
  fake.respond(1, { texto: "Olá", trechos: [] });
  assert.equal((await transcribing).texto, "Olá");
});

test("cancelamento termina worker e rejeita operação ativa", async () => {
  const fake = new FakeWorker();
  const client = new BrowserWhisperWorker(() => fake);
  const running = client.load("small");
  client.terminate();
  await assert.rejects(running, /cancelada/);
  assert.equal(fake.terminated, true);
  assert.equal(client.pending.size, 0);
  assert.equal(client.worker, null);
});

test("erro no worker libera estado e permite tentar novamente", async () => {
  const created = [];
  const client = new BrowserWhisperWorker(() => { const fake = new FakeWorker(); created.push(fake); return fake; });
  const first = client.load("base");
  created[0].onerror({ preventDefault() {} });
  await assert.rejects(first, /Falha ao carregar/);
  const second = client.load("base");
  created[1].respond(0, true);
  await second;
  assert.equal(created.length, 2);
});
