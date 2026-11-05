"""Diagnóstico sem baixar modelos nem ler gravações."""
import os
import platform
import sys
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctranslate2
from transcription_core import MODEL_DIRECTORY

print("Python:", platform.python_version(), platform.architecture()[0])
print("Sistema:", platform.system(), platform.machine())
print("CPUs lógicas:", os.cpu_count())
for dependency in ("streamlit", "faster-whisper", "ctranslate2", "imageio-ffmpeg"):
    print(f"{dependency}: {version(dependency)}")
print("Pasta dos modelos:", MODEL_DIRECTORY)
try:
    count = ctranslate2.get_cuda_device_count()
    print("Dispositivos CUDA detectados:", count)
    if count:
        print("Tipos de cálculo CUDA:", ", ".join(sorted(ctranslate2.get_supported_compute_types("cuda"))))
        print("A inferência ainda exige cuBLAS/CUDA 12 e cuDNN 9 funcionais.")
    else:
        print("Use CPU. GPU AMD/Intel e Apple Metal não são acelerados por este backend.")
except RuntimeError as exc:
    print("CUDA indisponível:", exc)
    print("Use CPU.")

