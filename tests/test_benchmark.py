"""Benchmark preparation must run without models and never emit transcriptions."""
import subprocess
import tempfile
import unittest
from pathlib import Path

import imageio_ffmpeg
from scripts.benchmark import process_file


class BenchmarkTests(unittest.TestCase):
    def test_prepare_only_provides_metrics_without_loading_asr(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "teste.mp3"
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                            "-y", str(file)], check=True, capture_output=True)
            report = process_file(file, prep_only=True, model="large-v3", device="cpu", reference=None,
                                  chunk_minutes=1)
            self.assertFalse(report["recognition_tested"])
            self.assertFalse(report["reference_tested"])
            self.assertEqual(report["expected_parts"], 1)
            self.assertGreater(report["pcm_size_bytes"], report["file_size_bytes"])
            self.assertAlmostEqual(report["duration_seconds"], 2, delta=0.2)
            self.assertNotIn("original", report)
            self.assertNotIn("wer", report)
