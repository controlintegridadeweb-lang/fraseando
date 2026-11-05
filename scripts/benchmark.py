"""Run a reproducible local MP3/MP4 benchmark, optionally measuring WER.

Examples:
  python scripts/benchmark.py reuniao.mp3 --preparo-apenas
  python scripts/benchmark.py reuniao.mp3 --modelo large-v3 --referencia humana.txt

The default ASR mode expects a model already cached locally and never uploads audio.
No transcription content is printed or included in the JSON report.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from transcription_core import (ModelSettings, calculate_accuracy, convert_to_wav,
                                get_transcriber, transcribe_wav_in_parts, wav_duration)


def process_file(path: Path, *, prep_only: bool, model: str, device: str,
                 reference: Path | None, chunk_minutes: int = 20, offline: bool = True) -> dict:
    """Measure wall time and real PCM preparation; optional real inference/quality."""
    if not 1 <= chunk_minutes <= 180:
        raise ValueError("O tamanho da parte deve estar entre 1 e 180 minutos.")
    report = {"file_size_bytes": path.stat().st_size, "machine": platform.platform(),
              "python": platform.python_version(), "model": None if prep_only else model,
              "device": None if prep_only else device, "recognition_tested": not prep_only,
              "reference_tested": reference is not None and not prep_only}
    with tempfile.TemporaryDirectory(prefix="fraseado_benchmark_") as tmp:
        t0 = time.perf_counter()
        wav = convert_to_wav(path, Path(tmp))
        report["prep_seconds"] = round(time.perf_counter() - t0, 3)
        report["duration_seconds"] = round(wav_duration(wav), 3)
        report["pcm_size_bytes"] = wav.stat().st_size
        report["expected_parts"] = math.ceil(report["duration_seconds"] / (chunk_minutes * 60))
        if not prep_only:
            t1 = time.perf_counter()
            engine = get_transcriber(ModelSettings(model=model, device=device, offline=offline))
            report["model_load_seconds"] = round(time.perf_counter() - t1, 3)
            t2 = time.perf_counter()
            result = transcribe_wav_in_parts(engine, wav, max_part_seconds=chunk_minutes * 60)
            report["transcription_wall_seconds"] = round(time.perf_counter() - t2, 3)
            report["real_time_factor"] = round(report["transcription_wall_seconds"] / report["duration_seconds"], 4)
            report["recognized_parts"] = result["audio_parts"]
            report["words"] = len(result["original"].split())
            if reference:
                accuracy = calculate_accuracy(reference.read_text(encoding="utf-8"), result["original"])
                report["wer"] = round(accuracy["wer"], 5)
                report["score_percent"] = round(accuracy["score"], 3)
                report["reference_words"] = accuracy["reference_words"]
    # ru_maxrss is process high-water mark on Unix; not directly comparable across OS.
    if os.name == "posix":
        import resource
        report["peak_rss_raw_ru_maxrss"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report["rss_unit"] = "KiB on Linux; bytes on macOS"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark local do Fraseado (sem upload)")
    parser.add_argument("arquivo", type=Path, help="MP3 ou MP4 de referência")
    parser.add_argument("--preparo-apenas", action="store_true", help="Não baixa ou executa modelos ASR")
    parser.add_argument("--modelo", choices=["large-v3", "turbo", "medium", "small", "tiny"], default="small")
    parser.add_argument("--dispositivo", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--permitir-download-modelo", action="store_true", help="Permite obter pesos ausentes")
    parser.add_argument("--referencia", type=Path, help="TXT humano da mesma gravação, para WER")
    parser.add_argument("--minutos-por-parte", type=int, default=20)
    parser.add_argument("--saida", type=Path, help="Caminho opcional para o JSON sem transcrição")
    args = parser.parse_args()
    if args.referencia and args.preparo_apenas:
        parser.error("--referencia exige reconhecimento real; retire --preparo-apenas")
    try:
        report = process_file(args.arquivo, prep_only=args.preparo_apenas, model=args.modelo,
                              device=args.dispositivo, reference=args.referencia,
                              chunk_minutes=args.minutos_por_parte,
                              offline=not args.permitir_download_modelo)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Falha na validação: {exc}\n")
    output = json.dumps(report, indent=2, ensure_ascii=False)
    print(output)
    if args.saida:
        args.saida.write_text(output + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
