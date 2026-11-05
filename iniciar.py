"""Instala o ambiente isolado e abre o Fraseando; não exige ativação manual."""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(args: list[str]) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fraseando local")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--instalar", action="store_true", help="Instala as dependências e encerra")
    actions.add_argument("--testar", action="store_true", help="Executa testes, sem baixar modelos")
    actions.add_argument("--diagnostico", action="store_true", help="Mostra ambiente e suporte a CUDA")
    actions.add_argument("--baixar-modelo", choices=["large-v3", "turbo", "medium", "small", "tiny"])
    args = parser.parse_args()
    if not (3, 11) <= sys.version_info[:2] <= (3, 13):
        print("Use Python 3.11, 3.12 ou 3.13 de 64 bits. Recomendado: Python 3.12.")
        return 1
    if sys.maxsize <= 2**32:
        print("É necessário Python de 64 bits.")
        return 1
    if not PYTHON.is_file():
        print("Criando o ambiente .venv...", flush=True)
        venv.EnvBuilder(with_pip=True).create(ROOT / ".venv")
    requirement_hash = hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest()
    stamp = ROOT / ".venv" / ".fraseado_requirements"
    if not stamp.exists() or stamp.read_text().strip() != requirement_hash:
        print("Instalando dependências. Esta etapa precisa de internet.", flush=True)
        run([str(PYTHON), "-m", "pip", "install", "-r", "requirements.txt"])
        run([str(PYTHON), "-m", "pip", "check"])
        stamp.write_text(requirement_hash)
    if args.instalar:
        print("Instalação concluída. Execute: python iniciar.py")
    elif args.testar:
        run([str(PYTHON), "-m", "unittest", "discover", "-s", "tests", "-v"])
        if shutil.which("node"):
            run(["node", "--test", "tests/browser_utils.test.mjs"])
        else:
            print("Node.js não instalado: testes web não executados. Instale Node 22+ para a suíte completa.")
    elif args.diagnostico:
        run([str(PYTHON), "scripts/diagnostico.py"])
    elif args.baixar_modelo:
        run([str(PYTHON), "scripts/baixar_modelo.py", args.baixar_modelo])
    else:
        print("Fraseando: http://127.0.0.1:8501 | Ctrl+C para encerrar.", flush=True)
        run([str(PYTHON), "-m", "streamlit", "run", "app.py"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nFraseando encerrado.")
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Não foi possível concluir: {exc}", file=sys.stderr)
        raise SystemExit(1)

