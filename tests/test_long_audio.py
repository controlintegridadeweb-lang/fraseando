"""Stress tests use a synthetic hour; they never pretend to measure ASR accuracy."""
import os
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

import imageio_ffmpeg
from transcription_core import convert_to_wav, transcribe_wav_in_parts, wav_duration


class LongAudioTests(unittest.TestCase):
    def test_incremental_splitting_reuses_one_temporary_wav(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "audio.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                for _ in range(75):
                    audio.writeframes(b"\0\0" * 16000)
            seen = []
            def transcribe(file, **_):
                observed = list(Path(file).parent.glob("*.wav"))
                self.assertEqual(len(observed), 1, "Duplicação de WAVs temporários")
                seen.append(Path(file).stat().st_size)
                return {"original": "fala", "parts": [{"start": 0, "end": 0.5, "text": "fala"}],
                        "elapsed": 0.1, "model": "small", "device": "cpu"}
            result = transcribe_wav_in_parts(SimpleNamespace(transcribe=transcribe), path,
                                             max_part_seconds=20)
            self.assertEqual(result["audio_parts"], 4)
            self.assertEqual(len(seen), 4)
            self.assertEqual(len(list(Path(root).rglob("parte_atual.wav"))), 0)
            self.assertAlmostEqual(result["parts"][-1]["start"], 60)

    @unittest.skipUnless(os.environ.get("FRASEADO_STRESS") == "1",
                         "Use FRASEADO_STRESS=1 para testar uma hora sintética de MP3")
    def test_one_hour_mp3_to_pcm_and_incremental_parts(self):
        with tempfile.TemporaryDirectory(prefix="fraseado_stress_") as root:
            media = Path(root) / "uma_hora.mp3"
            cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
                   "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "3600",
                   "-b:a", "32k", "-y", str(media)]
            subprocess.run(cmd, check=True, capture_output=True, timeout=300)
            wav = convert_to_wav(media, Path(root) / "out")
            self.assertAlmostEqual(wav_duration(wav), 3600, delta=1)
            count = 0
            def transcribe(file, **_):
                nonlocal count
                count += 1
                self.assertLessEqual(Path(file).stat().st_size, 20 * 60 * 16000 * 2 + 64)
                return {"original": "", "parts": [], "elapsed": 0,
                        "model": "simulated", "device": "cpu"}
            result = transcribe_wav_in_parts(SimpleNamespace(transcribe=transcribe), wav,
                                             max_part_seconds=20 * 60)
            self.assertEqual(count, 3)
            self.assertEqual(result["audio_parts"], 3)
