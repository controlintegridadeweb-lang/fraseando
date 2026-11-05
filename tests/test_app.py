"""Testes da interface sem rede, modelos ou arquivos particulares."""
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None


@unittest.skipUnless(AppTest is not None, "Streamlit não instalado")
class AppTests(unittest.TestCase):
    def open_app(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
        with patch("transcription_core.get_transcriber", side_effect=AssertionError("Download inesperado")):
            app.run(timeout=20)
        self.assertFalse(app.exception)
        return app

    def test_start_disabled_until_file_is_uploaded(self):
        app = self.open_app()
        self.assertEqual(app.title[0].value, "Sua gravação, em texto.")
        self.assertTrue(app.button[0].disabled)
        self.assertEqual(app.selectbox[0].value, "large-v3")
        self.assertEqual(app.selectbox[1].value, "cpu")
        self.assertFalse(app.text_input)  # Nenhum campo de chave de API.
        split = next(x for x in app.checkbox if "Dividir" in x.label)
        self.assertTrue(split.value)
        limit = next(x for x in app.number_input if "Cada parte" in x.label)
        self.assertEqual(limit.value, 20)

    def test_change_model_and_enable_offline_without_download(self):
        app = self.open_app()
        app.selectbox[0].select("turbo")
        app.checkbox[0].check()
        with patch("transcription_core.get_transcriber", side_effect=AssertionError("Download inesperado")):
            app.run(timeout=20)
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox[0].value, "turbo")
        self.assertTrue(app.checkbox[0].value)
        self.assertTrue(app.button[0].disabled)

    def test_clear_stale_result_without_file(self):
        app = self.open_app()
        app.session_state["file_id"] = "old-upload"
        app.session_state["transcription"] = {"file_id": "old-upload", "original": "texto antigo"}
        app.session_state["editor"] = "texto antigo"
        app.run(timeout=20)
        self.assertFalse(app.exception)
        self.assertNotIn("transcription", app.session_state.filtered_state)




@unittest.skipUnless(AppTest is not None, "Streamlit não instalado")
class TranscriptionFlowTests(unittest.TestCase):
    def test_upload_transcribe_edit_export_and_measure_original(self):
        import io
        import subprocess
        import tempfile
        import wave
        from types import SimpleNamespace
        from unittest.mock import Mock
        import imageio_ffmpeg

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wav = root / "original.wav"
            with wave.open(str(wav), "wb") as audio:
                audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\x00\x00" * 16000)
            mp3 = root / "original.mp3"
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-y",
                            "-i", str(wav), str(mp3)], check=True)
            upload = io.BytesIO(mp3.read_bytes())
            upload.name = "reuniao.mp3"
            upload.size = len(upload.getbuffer())
            result = {"original": "Olá mundo", "parts": [{"part": 1, "start": 0, "end": 1,
                       "text": "Olá mundo"}], "duration": 1, "elapsed": 0.1,
                       "model": "small", "device": "cpu"}
            engine = SimpleNamespace(transcribe=Mock(return_value=result))
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
            with patch("streamlit.file_uploader", return_value=upload), \
                    patch("transcription_core.get_transcriber", return_value=engine):
                app.run(timeout=20)
                app.button[0].click().run(timeout=20)
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["transcription"]["original"], "Olá mundo")
                engine.transcribe.assert_called_once()
                next(x for x in app.text_area if x.label == "Texto transcrito (editável)").set_value("Texto corrigido")
                app.run(timeout=20)
                next(x for x in app.text_area if x.label == "Transcrição de referência").set_value("Olá mundo")
                app.run(timeout=20)
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["editor"], "Texto corrigido")
                self.assertEqual(app.session_state["transcription"]["original"], "Olá mundo")
                score = next(x for x in app.metric if x.label == "Pontuação 1 − WER")
                self.assertEqual(score.value, "100.00%")
                self.assertEqual(len(app.get("download_button")), 4)


if __name__ == "__main__":
    unittest.main()

