"""Transcrição local com Faster Whisper, preparo de mídia e avaliação WER."""
from __future__ import annotations

import math
import gc
import os
import re
import subprocess
import tempfile
import threading
import time
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import imageio_ffmpeg
from rapidfuzz.distance import Levenshtein

ALLOWED_EXTENSIONS = {".mp3", ".mp4"}
MODEL_NAMES = ("large-v3", "turbo", "medium", "small", "tiny")
PROJECT_ROOT = Path(__file__).resolve().parent
MODEL_DIRECTORY = PROJECT_ROOT / ".models"


class TranscriptionError(RuntimeError):
    """Erro legível na interface."""


@dataclass(frozen=True)
class ModelSettings:
    model: str = "large-v3"
    device: str = "cpu"
    cpu_threads: int = min(8, os.cpu_count() or 1)
    offline: bool = False
    cache_directory: str = str(MODEL_DIRECTORY)

    def __post_init__(self) -> None:
        if self.model not in MODEL_NAMES:
            raise ValueError("Modelo local não suportado.")
        if self.device not in {"cpu", "cuda"}:
            raise ValueError("Escolha CPU ou CUDA.")
        if not 1 <= self.cpu_threads <= 64:
            raise ValueError("Use entre 1 e 64 threads de CPU.")

    @property
    def compute_type(self) -> str:
        return "int8" if self.device == "cpu" else "float16"


def convert_to_wav(source: Path, directory: Path) -> Path:
    """Extrai a primeira faixa de áudio em PCM mono, sem recompressão MP3."""
    source = Path(source).resolve()
    if source.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("Formato não permitido. Envie MP3 ou MP4.")
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError("O arquivo está vazio ou não foi encontrado.")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "audio_convertido.wav"
    result = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
         "-nostdin", "-protocol_whitelist", "file,pipe", "-y", "-i", str(source),
         "-map", "0:a:0", "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(target)],
        capture_output=True, text=True, timeout=1800, check=False,
    )
    if result.returncode:
        raise TranscriptionError(
            "Não foi possível ler a faixa de áudio. Confira se o MP3/MP4 abre normalmente "
            "em um reprodutor e se o vídeo contém som."
        )
    wav_duration(target)
    return target


def wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio:
            seconds = audio.getnframes() / audio.getframerate()
    except (wave.Error, EOFError, OSError, ZeroDivisionError) as exc:
        raise TranscriptionError("Não foi possível ler o áudio preparado.") from exc
    if seconds <= 0:
        raise TranscriptionError("O arquivo não possui duração válida.")
    return seconds


def split_wav(path: Path, directory: Path, max_seconds: float) -> list[dict]:
    """Corta o WAV em trechos de no máximo max_seconds, sem recomprimir."""
    if not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("A duração máxima de cada parte deve ser positiva.")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    chunks: list[dict] = []
    with wave.open(str(path), "rb") as source:
        params = source.getparams()
        rate = source.getframerate()
        sample_bytes = source.getsampwidth() * source.getnchannels()
        frames_per_chunk = max(1, int(rate * max_seconds))
        start_frame = 0
        index = 0
        while True:
            frames = source.readframes(frames_per_chunk)
            if not frames:
                break
            nframes = len(frames) // sample_bytes
            if nframes <= 0:
                break
            index += 1
            target = directory / f"parte_{index:03d}.wav"
            with wave.open(str(target), "wb") as output:
                output.setparams(params)
                output.writeframes(frames)
            chunks.append({
                "path": target,
                "index": index,
                "start": start_frame / rate,
                "duration": nframes / rate,
            })
            start_frame += nframes
    if not chunks:
        raise TranscriptionError("Não foi possível dividir o áudio preparado.")
    return chunks


def encode_wav_as_mp3(source: Path, target: Path) -> Path:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
         "-nostdin", "-protocol_whitelist", "file,pipe", "-y", "-i", str(source),
         "-c:a", "libmp3lame", "-q:a", "4", str(target)],
        capture_output=True, text=True, timeout=1800, check=False,
    )
    if result.returncode or not target.is_file() or target.stat().st_size == 0:
        raise TranscriptionError("Não foi possível gravar a parte de áudio em MP3.")
    return target


def merge_part_results(
    chunks: Sequence[dict], results: Sequence[dict], total_duration: float,
) -> dict:
    if len(chunks) != len(results):
        raise ValueError("O número de trechos e de transcrições não coincide.")
    parts: list[dict] = []
    originals: list[str] = []
    elapsed = 0.0
    model = results[0]["model"] if results else ""
    device = results[0]["device"] if results else ""
    saved: list[str] = []
    for chunk, result in zip(chunks, results):
        elapsed += float(result["elapsed"])
        offset = float(chunk["start"])
        if result["original"]:
            originals.append(result["original"])
        for part in result["parts"]:
            parts.append({
                "part": len(parts) + 1,
                "start": float(part["start"]) + offset,
                "end": float(part["end"]) + offset,
                "text": part["text"],
            })
        if chunk.get("mp3"):
            saved.append(str(chunk["mp3"]))
    return {
        "original": "\n".join(originals),
        "parts": parts,
        "duration": total_duration,
        "elapsed": elapsed,
        "model": model,
        "device": device,
        "audio_parts": len(chunks),
        "saved_parts": saved,
    }


def _iter_wav_parts(path: Path, directory: Path, max_seconds: float):
    """Produce one WAV part at a time, writing in small buffers instead of all parts.

    The output name is intentionally reused after each part has been consumed.
    A one-hour input therefore needs space for the original PCM plus only one part.
    """
    with wave.open(str(path), "rb") as source:
        params = source.getparams()
        rate = source.getframerate()
        frames_per_part = max(1, int(rate * max_seconds))
        buffer_frames = max(1, min(rate * 5, frames_per_part))
        start_frame = 0
        part_number = 0
        total_frames = source.getnframes()
        while start_frame < total_frames:
            part_number += 1
            target = directory / "parte_atual.wav"
            written = 0
            with wave.open(str(target), "wb") as output:
                output.setparams(params)
                while written < frames_per_part and start_frame + written < total_frames:
                    frames = source.readframes(min(buffer_frames, frames_per_part - written))
                    if not frames:
                        break
                    frame_count = len(frames) // (params.sampwidth * params.nchannels)
                    output.writeframesraw(frames)
                    written += frame_count
            if written == 0:
                raise TranscriptionError("Não foi possível ler uma parte do áudio preparado.")
            yield {"path": target, "index": part_number, "start": start_frame / rate,
                   "duration": written / rate}
            start_frame += written
            target.unlink(missing_ok=True)


def transcribe_wav_in_parts(
    engine: LocalTranscriber,
    audio: Path,
    *,
    max_part_seconds: float | None = None,
    context: str = "",
    keywords: Sequence[str] = (),
    on_progress: Callable[[float, str], None] | None = None,
    split_directory: Path | None = None,
) -> dict:
    """Transcribe while retaining at most one temporary WAV chunk on disk."""
    duration = wav_duration(audio)
    if max_part_seconds is None or duration <= max_part_seconds:
        result = engine.transcribe(
            audio, context=context, keywords=keywords, on_progress=on_progress,
        )
        result["audio_parts"] = 1
        result["saved_parts"] = []
        return result
    if not math.isfinite(max_part_seconds) or max_part_seconds <= 0:
        raise ValueError("A duração máxima de cada parte deve ser positiva.")

    count = math.ceil(duration / max_part_seconds)
    chunks: list[dict] = []
    results: list[dict] = []
    # TemporaryDirectory removes even an incomplete part on an exception.
    with tempfile.TemporaryDirectory(prefix="fraseado_partes_") as tmp:
        for index, chunk in enumerate(_iter_wav_parts(Path(audio), Path(tmp), max_part_seconds)):
            def update(fraction: float, text: str, current: int = index) -> None:
                if on_progress:
                    on_progress(min(0.99, (current + max(0.0, fraction)) / count), text)

            result = engine.transcribe(
                chunk["path"], context=context, keywords=keywords,
                on_progress=update if on_progress else None,
            )
            if split_directory is not None:
                name = f"parte_{chunk['index']:03d}.mp3"
                chunk["mp3"] = encode_wav_as_mp3(chunk["path"], Path(split_directory) / name)
            chunks.append(chunk)
            results.append(result)
    merged = merge_part_results(chunks, results, duration)
    if on_progress:
        on_progress(1.0, "")
    return merged


def parse_keywords(text: str) -> list[str]:
    clean: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        word = raw.strip()
        if word and len(word) <= 80 and not any(ch in word for ch in "<>\r\n"):
            if word.casefold() not in seen:
                clean.append(word)
                seen.add(word.casefold())
    return clean[:40]


def build_prompt(context: str = "", keywords: Sequence[str] = ()) -> str | None:
    # Nomes têm prioridade. O contexto do Whisper é limitado em tokens.
    terms = ", ".join(keywords)[:600]
    hints = [f"Vocabulário: {terms}."] if terms else []
    if context.strip():
        hints.append(context.strip()[:300])
    return " ".join(hints)[:900] or None


class LocalTranscriber:
    """Um modelo em memória; o lock cobre a iteração lazy dos segmentos."""

    def __init__(self, settings: ModelSettings):
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        from faster_whisper import WhisperModel

        self.settings = settings
        self.lock = threading.Lock()
        try:
            self.model = WhisperModel(
                settings.model, device=settings.device, compute_type=settings.compute_type,
                cpu_threads=settings.cpu_threads, num_workers=1,
                download_root=settings.cache_directory, local_files_only=settings.offline,
            )
        except Exception as exc:
            if settings.offline:
                advice = "O modelo precisa estar baixado nesta pasta. Desative o modo offline para baixá-lo."
            elif settings.device == "cuda":
                advice = "Confira a GPU NVIDIA, CUDA 12 e cuDNN 9 ou selecione CPU."
            else:
                advice = "Confira a conexão para baixar o modelo, o espaço em disco e a memória disponível."
            raise TranscriptionError(f"Não foi possível carregar {settings.model}. {advice}") from exc

    def transcribe(
        self, audio: Path, *, context: str = "", keywords: Sequence[str] = (),
        on_progress: Callable[[float, str], None] | None = None,
    ) -> dict:
        duration = wav_duration(audio)
        started = time.monotonic()
        parts: list[dict] = []
        with self.lock:
            if self.model is None:
                raise TranscriptionError("O modelo foi trocado. Inicie a transcrição novamente.")
            segments, _info = self.model.transcribe(
                str(audio), language="pt", task="transcribe", beam_size=5,
                initial_prompt=build_prompt(context, keywords),
                vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=False,
            )
            for segment in segments:
                text = segment.text.strip()
                if text:
                    parts.append({"part": len(parts) + 1, "start": float(segment.start),
                                  "end": float(segment.end), "text": text})
                if on_progress:
                    on_progress(min(0.99, max(0.0, float(segment.end) / duration)), text)
        if on_progress:
            on_progress(1.0, "")
        return {"original": "\n".join(part["text"] for part in parts), "parts": parts,
                "duration": duration, "elapsed": time.monotonic() - started,
                "model": self.settings.model, "device": self.settings.device}

    def close(self) -> None:
        with self.lock:
            self.model = None
        gc.collect()


_cached_transcriber: LocalTranscriber | None = None
_cache_lock = threading.Lock()


def clear_model_cache() -> None:
    global _cached_transcriber
    with _cache_lock:
        if _cached_transcriber is not None:
            _cached_transcriber.close()
            _cached_transcriber = None


def get_transcriber(settings: ModelSettings) -> LocalTranscriber:
    """Libera o modelo anterior antes de carregar outro, evitando memória duplicada."""
    global _cached_transcriber
    def identity(value: ModelSettings) -> tuple:
        # Um modelo já carregado também pode ser usado quando o modo offline é ativado.
        return value.model, value.device, value.cpu_threads, value.cache_directory
    with _cache_lock:
        if _cached_transcriber is not None:
            if identity(_cached_transcriber.settings) == identity(settings):
                return _cached_transcriber
            _cached_transcriber.close()
            _cached_transcriber = None
        _cached_transcriber = LocalTranscriber(settings)
        return _cached_transcriber


def _timestamp(seconds: float, separator: str) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Timestamp inválido.")
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02}{separator}{millis:03}"


def export_subtitles(parts: Sequence[dict], kind: str = "srt") -> str:
    if kind not in {"srt", "vtt"}:
        raise ValueError("Formato de legenda inválido.")
    separator = "," if kind == "srt" else "."
    blocks: list[str] = []
    for part in parts:
        text = str(part["text"]).strip()
        if not text:
            continue
        start, end = float(part["start"]), float(part["end"])
        if end < start:
            raise ValueError("O fim do trecho precede o início.")
        blocks.append(
            f"{len(blocks) + 1}\n{_timestamp(start, separator)} --> {_timestamp(end, separator)}\n{text}"
        )
    content = "\n\n".join(blocks)
    return ("WEBVTT\n\n" if kind == "vtt" else "") + content + ("\n" if content else "")


def calculate_accuracy(reference: str, hypothesis: str) -> dict[str, float | int]:
    """Pontuação 1-WER; nunca uma confiança estimada pelo modelo."""
    def tokens(value: str) -> list[str]:
        return re.findall(r"[^\W_]+", unicodedata.normalize("NFC", value).casefold(), flags=re.UNICODE)

    ref, hyp = tokens(reference), tokens(hypothesis)
    if not ref:
        raise ValueError("Forneça uma transcrição de referência com palavras.")
    edits = Levenshtein.distance(ref, hyp)
    wer = edits / len(ref)
    return {"reference_words": len(ref), "transcribed_words": len(hyp),
            "word_errors": edits, "wer": wer, "score": max(0.0, (1.0 - wer) * 100)}

