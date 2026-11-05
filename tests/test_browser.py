"""Browser integration against a fake, deterministic Whisper worker (no model downloads).

Optional: install playwright+Chromium or set FRASEADO_CHROME to a Chromium executable.
These tests verify DOM/flows, *not* ASR accuracy or the third-party model bundle.
"""
import functools
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import imageio_ffmpeg

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]
MOCK_WORKER = """
self.onmessage = ({data}) => {
  if (data.type === 'load') {
    self.postMessage({ id:data.id, type:'result', value:true });
  } else if (data.type === 'transcribe') {
    setTimeout(() => self.postMessage({ id:data.id, type:'result', value: {
      texto:'Olá mundo', trechos:[{text:'Olá mundo', start:0.125, end:0.875}]
    } }), 1400);
  }
};
"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(sync_playwright is not None and os.environ.get("FRASEADO_BROWSER_E2E") == "1",
                     "Use FRASEADO_BROWSER_E2E=1 com Chromium e rede local habilitada")
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="fraseado_browser_")
        cls.file = Path(cls.temp.name) / "audio.mp3"
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-y", str(cls.file)],
                       capture_output=True, check=True)
        handler = functools.partial(QuietHandler, directory=str(ROOT / "docs"))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.playwright = sync_playwright().start()
        executable = os.environ.get("FRASEADO_CHROME") or shutil.which("chromium") or shutil.which("google-chrome")
        try:
            cls.browser = cls.playwright.chromium.launch(
                executable_path=executable, headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--no-proxy-server", "--proxy-bypass-list=<-loopback>"])
        except Exception as error:
            cls.tearDownClass()
            raise unittest.SkipTest(f"Chromium indisponível: {error}") from error

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "browser"): cls.browser.close()
        if hasattr(cls, "playwright"): cls.playwright.stop()
        if hasattr(cls, "server"):
            cls.server.shutdown()
            cls.server.server_close()
        if hasattr(cls, "temp"): cls.temp.cleanup()

    def setUp(self):
        self.context = self.browser.new_context(accept_downloads=True)
        self.context.route("**/transcriber.worker.js", lambda route: route.fulfill(
            status=200, content_type="text/javascript", body=MOCK_WORKER))
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(self.url, wait_until="domcontentloaded")
        self.page.locator("#arquivo").set_input_files(str(self.file))
        self.page.locator("#iniciar").wait_for(state="visible")
        self.page.wait_for_function("!document.querySelector('#iniciar').disabled")

    def tearDown(self):
        self.context.close()

    def test_transcribe_and_download_srt_and_vtt(self):
        self.page.locator("#iniciar").click()
        self.page.locator("#resultado").wait_for(state="visible", timeout=15000)
        self.assertEqual(self.page.locator("#editor").input_value(), "Olá mundo")
        with self.page.expect_download() as download_event:
            self.page.locator("#baixar-srt").click()
        download = download_event.value
        self.assertTrue(download.suggested_filename.endswith(".srt"))
        path = download.path()
        self.assertIn("00:00:00,125 --> 00:00:00,875", Path(path).read_text())
        with self.page.expect_download() as download_event:
            self.page.locator("#baixar-vtt").click()
        self.assertIn("WEBVTT", Path(download_event.value.path()).read_text())
        self.assertEqual(self.errors, [])

    def test_cancel_and_resume(self):
        self.page.locator("#iniciar").click()
        self.page.locator("#cancelar").wait_for(state="visible", timeout=6000)
        self.page.locator("#cancelar").click()
        self.page.get_by_text("Cancelado", exact=False).first.wait_for(timeout=10000)
        self.page.wait_for_function("!document.querySelector('#iniciar').disabled")
        self.assertEqual(self.errors, [])
        self.page.locator("#continuar").click()
        self.page.locator("#resultado").wait_for(state="visible", timeout=15000)
        self.assertEqual(self.page.locator("#editor").input_value(), "Olá mundo")
