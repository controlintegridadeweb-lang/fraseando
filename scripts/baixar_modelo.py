"""Prepara um modelo para uso offline posterior."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transcription_core import MODEL_DIRECTORY, MODEL_NAMES, ModelSettings, get_transcriber

parser = argparse.ArgumentParser()
parser.add_argument("modelo", choices=MODEL_NAMES, nargs="?", default="large-v3")
args = parser.parse_args()
print(f"Baixando/carregando {args.modelo}. Aguarde; o Large v3 ocupa alguns GB.", flush=True)
get_transcriber(ModelSettings(model=args.modelo))
print("Modelo pronto em:", MODEL_DIRECTORY)

