import importlib.util
import subprocess
import sys
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import imageio_ffmpeg

from transcription_core import (
    LocalTranscriber, ModelSettings, TranscriptionError, build_prompt,
    calculate_accuracy, convert_to_wav, encode_wav_as_mp3, export_subtitles,
    merge_part_results, parse_keywords, split_wav, transcribe_wav_in_parts,
    wav_duration, clear_model_cache, get_transcriber,
)


def make_wav(path, seconds=2):
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * int(16000 * seconds))


class AccuracyTests(unittest.TestCase):
    def test_normalization_and_accents(self):
        self.assertEqual(calculate_accuracy("Olá, AÇÃO!", "olá ação")["score"], 100)
        self.assertEqual(calculate_accuracy("ação", "acao")["word_errors"], 1)

    def test_insertions_deletions_and_score_floor(self):
        self.assertEqual(calculate_accuracy("um dois três quatro", "um dois quatro")["score"], 75)
        self.assertEqual(calculate_accuracy("um", "dois três quatro")["score"], 0)

    def test_punctuation_only_reference(self):
        with self.assertRaises(ValueError):
            calculate_accuracy("... !!!", "testando")

    def test_keywords_and_prompt(self):
        words = parse_keywords("SEPLAN\nPPA\nseplan\n<tag>")
        self.assertEqual(words, ["SEPLAN", "PPA"])
        self.assertIn("SEPLAN", build_prompt("orçamento", words))
        self.assertLessEqual(len(build_prompt("x" * 1000, ["y" * 80] * 40)), 900)
        self.assertIsNone(build_prompt())


class MediaTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("faster_whisper"), "faster-whisper não instalado")
    def test_faster_whisper_audio_decoder_compatibility(self):
        from faster_whisper.audio import decode_audio
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "decoder.wav"
            make_wav(path, seconds=1)
            samples = decode_audio(str(path), sampling_rate=16000)
            self.assertEqual(len(samples), 16000)

    def test_real_mp3_and_mp4_conversion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wav = root / "input.wav"
            make_wav(wav)
            for suffix, codec in (("mp3", "libmp3lame"), ("mp4", "aac")):
                media = root / ("recording." + suffix)
                command = [imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error",
                           "-y", "-i", str(wav), "-c:a", codec, str(media)]
                subprocess.run(command, check=True, capture_output=True)
                converted = convert_to_wav(media, root / suffix)
                with wave.open(str(converted), "rb") as audio:
                    self.assertEqual(audio.getframerate(), 16000)
                    self.assertEqual(audio.getnchannels(), 1)
                    self.assertEqual(audio.getsampwidth(), 2)
                self.assertAlmostEqual(wav_duration(converted), 2, delta=0.2)

    def test_video_without_audio_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "silent_video.mp4"
            subprocess.run(
                [imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i", "color=c=black:s=32x32:d=1", "-an", str(path)],
                check=True, capture_output=True,
            )
            with self.assertRaises(TranscriptionError):
                convert_to_wav(path, Path(folder) / "out")

    def test_invalid_media_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(ValueError):
                convert_to_wav(root / "missing.mp3", root)
            bad = root / "bad.mp4"
            bad.write_bytes(b"not a video")
            with self.assertRaises(TranscriptionError):
                convert_to_wav(bad, root)


class SplitAudioTests(unittest.TestCase):
    def test_short_audio_stays_in_one_part(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "short.wav"
            make_wav(path, seconds=5)
            chunks = split_wav(path, Path(folder) / "out", 20)
            self.assertEqual(len(chunks), 1)
            self.assertAlmostEqual(chunks[0]["duration"], 5, delta=0.05)
            self.assertAlmostEqual(wav_duration(chunks[0]["path"]), 5, delta=0.05)

    def test_splits_do_not_exceed_max_duration(self):
        # 50 s com teto de 20 s equivale a 1 h cortada a cada 20 min.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "long.wav"
            make_wav(path, seconds=50)
            chunks = split_wav(path, Path(folder) / "out", 20)
            self.assertEqual(len(chunks), 3)
            self.assertTrue(all(chunk["duration"] <= 20 + 1e-6 for chunk in chunks))
            self.assertAlmostEqual(sum(chunk["duration"] for chunk in chunks), 50, delta=0.05)
            self.assertAlmostEqual(chunks[1]["start"], 20, delta=0.05)

    def test_invalid_max_duration_is_rejected(self):
        with self.assertRaises(ValueError):
            split_wav(Path("x.wav"), Path("."), 0)

    def test_merge_shifts_timestamps_to_original_timeline(self):
        merged = merge_part_results(
            [{"start": 0}, {"start": 20, "mp3": r"C:\saidas\parte_002.mp3"}],
            [
                {"original": "um", "parts": [{"start": 1, "end": 2, "text": "um"}],
                 "elapsed": 0.1, "model": "small", "device": "cpu"},
                {"original": "dois", "parts": [{"start": 0.5, "end": 1, "text": "dois"}],
                 "elapsed": 0.2, "model": "small", "device": "cpu"},
            ],
            40,
        )
        self.assertEqual(merged["original"], "um\ndois")
        self.assertAlmostEqual(merged["parts"][1]["start"], 20.5)
        self.assertEqual(merged["audio_parts"], 2)
        self.assertEqual(len(merged["saved_parts"]), 1)

    def test_transcribe_in_parts_calls_engine_once_per_chunk(self):
        calls = []

        def transcribe(path, **kwargs):
            calls.append(path)
            if kwargs.get("on_progress"):
                kwargs["on_progress"](1.0, "fala")
            return {"original": "fala", "parts": [{"part": 1, "start": 0, "end": 0.5, "text": "fala"}],
                    "duration": 1, "elapsed": 0.01, "model": "small", "device": "cpu"}

        engine = SimpleNamespace(transcribe=transcribe)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "long.wav"
            make_wav(path, seconds=5)
            progress = []
            result = transcribe_wav_in_parts(
                engine, path, max_part_seconds=2,
                on_progress=lambda fraction, _: progress.append(fraction),
            )
        self.assertEqual(len(calls), 3)
        self.assertEqual(result["audio_parts"], 3)
        self.assertAlmostEqual(result["parts"][-1]["start"], 4.0, delta=0.05)
        self.assertEqual(progress[-1], 1)

    def test_wav_part_is_exported_as_mp3(self):
        with tempfile.TemporaryDirectory() as folder:
            wav = Path(folder) / "a.wav"
            mp3 = Path(folder) / "a.mp3"
            make_wav(wav, seconds=1)
            encode_wav_as_mp3(wav, mp3)
            self.assertGreater(mp3.stat().st_size, 0)


class EngineTests(unittest.TestCase):
    def tearDown(self):
        clear_model_cache()

    def test_offline_toggle_reuses_an_already_loaded_model(self):
        with patch("transcription_core.LocalTranscriber") as engine_class:
            engine_class.return_value.settings = ModelSettings(model="small")
            first = get_transcriber(ModelSettings(model="small"))
            second = get_transcriber(ModelSettings(model="small", offline=True))
            self.assertIs(first, second)
            self.assertEqual(engine_class.call_count, 1)

    def test_old_model_released_before_loading_new_model(self):
        events = []
        class FakeEngine:
            def __init__(self, settings):
                self.settings = settings
                events.append("load:" + settings.model)
            def close(self):
                events.append("close:" + self.settings.model)
        with patch("transcription_core.LocalTranscriber", FakeEngine):
            get_transcriber(ModelSettings(model="small"))
            get_transcriber(ModelSettings(model="medium"))
            self.assertEqual(events, ["load:small", "close:small", "load:medium"])
            clear_model_cache()

    @unittest.skipUnless(importlib.util.find_spec("faster_whisper"), "faster-whisper não instalado")
    def test_local_cpu_configuration_and_offline(self):
        with patch("faster_whisper.WhisperModel") as model:
            LocalTranscriber(ModelSettings(model="small", offline=True, cpu_threads=2))
            settings = model.call_args.kwargs
            self.assertEqual(settings["device"], "cpu")
            self.assertEqual(settings["compute_type"], "int8")
            self.assertTrue(settings["local_files_only"])
            self.assertEqual(settings["cpu_threads"], 2)

    def test_lazy_segments_are_consumed_and_original_text_preserved(self):
        events = []
        options = {}
        engine = LocalTranscriber.__new__(LocalTranscriber)
        engine.settings = ModelSettings()
        engine.lock = threading.Lock()

        def transcribe(path, **kwargs):
            options.update(kwargs)

            def generate():
                events.append("executed")
                yield SimpleNamespace(start=0, end=0.8, text=" Olá, mundo. ")
                yield SimpleNamespace(start=1, end=2, text=" PPA e SEPLAN. ")
            return generate(), SimpleNamespace()

        engine.model = SimpleNamespace(transcribe=transcribe)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "audio.wav"
            make_wav(path)
            progress = []
            result = engine.transcribe(path, keywords=["SEPLAN"],
                                       on_progress=lambda fraction, _: progress.append(fraction))
        self.assertEqual(events, ["executed"])
        self.assertEqual(result["original"], "Olá, mundo.\nPPA e SEPLAN.")
        self.assertEqual(len(result["parts"]), 2)
        self.assertEqual(progress[-1], 1)
        self.assertTrue(all(0 <= x <= 1 for x in progress))
        self.assertEqual(options["language"], "pt")
        self.assertTrue(options["vad_filter"])
        self.assertIn("SEPLAN", options["initial_prompt"])

    @unittest.skipUnless(importlib.util.find_spec("faster_whisper"), "faster-whisper não instalado")
    def test_model_load_failure_has_actionable_message(self):
        with patch("faster_whisper.WhisperModel", side_effect=RuntimeError("missing cache")):
            with self.assertRaisesRegex(TranscriptionError, "offline"):
                LocalTranscriber(ModelSettings(offline=True))

    def test_invalid_settings_do_not_load_model(self):
        with self.assertRaises(ValueError):
            ModelSettings(model="paid-api")
        with self.assertRaises(ValueError):
            ModelSettings(device="automatic")
        with self.assertRaises(ValueError):
            ModelSettings(cpu_threads=0)


class SubtitleTests(unittest.TestCase):
    def test_timestamp_rounding_carries_into_next_minute(self):
        parts = [{"start": 59.9999, "end": 3600.001, "text": "Olá."}]
        self.assertIn("00:01:00,000 --> 01:00:00,001", export_subtitles(parts))
        self.assertTrue(export_subtitles(parts, "vtt").startswith("WEBVTT\n\n"))
        self.assertIn("00:01:00.000", export_subtitles(parts, "vtt"))

    def test_empty_and_invalid_subtitles(self):
        self.assertEqual(export_subtitles([]), "")
        self.assertEqual(export_subtitles([], "vtt"), "WEBVTT\n\n")
        with self.assertRaises(ValueError):
            export_subtitles([{"start": 2, "end": 1, "text": "erro"}])


if __name__ == "__main__":
    unittest.main()

