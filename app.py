"""Fraseando — interface local e gratuita para MP3 e MP4."""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import streamlit as st

from transcription_core import (
    ModelSettings, PROJECT_ROOT, TranscriptionError, calculate_accuracy,
    convert_to_wav, export_subtitles, get_transcriber, parse_keywords,
    transcribe_wav_in_parts,
)

st.set_page_config(page_title="Fraseando | Transcrição local", page_icon="🎙️", layout="wide")
st.markdown("""
<style>
:root {
  --govbr-blue: #C45C16;
  --govbr-blue-dark: #8E3B0C;
  --govbr-navy: #4A220C;
  --govbr-green: #C45C16;
  --govbr-yellow: #E08A3A;
  --govbr-red: #B33A12;
  --govbr-text: #2F1E14;
  --govbr-muted: #6B4A38;
  --govbr-line: #E8D5C4;
  --govbr-surface: #FFFFFF;
  --govbr-canvas: #FBF4ED;
  --page-gutter: clamp(2.75rem, 8vw, 6rem);
}
html, body, [data-testid="stAppViewContainer"], .stApp, .stMarkdown, p, label, span {
  font-family: system-ui, "Segoe UI", Arial, sans-serif;
}
.stApp { background: var(--govbr-surface); color: var(--govbr-text); overflow-x: hidden; }
[data-testid="stMain"] { background: var(--govbr-canvas); }
[data-testid="stBottomBlockContainer"] { max-width: none !important; padding: 0 !important; }
header[data-testid="stHeader"] { background: var(--govbr-surface); height: 0; }
[data-testid="stDecoration"] { display: none; }
[data-testid="stSidebarHeader"],
[data-testid="stSidebarCollapsedControl"] {
  background: var(--govbr-surface);
}
[data-testid="stSidebarCollapseButton"] button,
[data-testid="stBaseButton-headerNoPadding"] {
  color: var(--govbr-blue);
}
#MainMenu, .stAppDeployButton { visibility: hidden; }
footer { visibility: hidden; }
.block-container {
  max-width: 100% !important;
  padding-top: 0 !important;
  padding-bottom: 0 !important;
  padding-left: 0 !important;
  padding-right: 0 !important;
}
h1, h2, h3 { color: var(--govbr-text); letter-spacing: 0; font-weight: 600; }
h1 { font-weight: 600; font-size: 1.85rem; margin-bottom: .2rem; }
h3 { font-size: 1.15rem; }
[data-testid="stSidebar"] {
  background: var(--govbr-surface);
  border-right: 1px solid var(--govbr-line);
}
[data-testid="stSidebar"] > div:first-child { background: var(--govbr-surface); }
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { color: var(--govbr-navy); }
.govbr-inner { max-width: 1140px; margin: 0 auto; }
.govbr-banner {
  padding: 0;
  background: #fff;
}
.govbr-banner-art {
  overflow: hidden;
  line-height: 0;
  width: 100%;
  aspect-ratio: 2000 / 393;
  background: #fff;
}
.govbr-banner-art img,
[data-testid="stElementContainer"]:has(.govbr-top) img {
  width: 100% !important;
  max-width: 100% !important;
  height: auto !important;
  max-height: none !important;
  display: block;
  object-fit: contain !important;
  object-position: top center !important;
}
.govbr-menu {
  position: relative;
  width: 100%;
  min-height: 3.1rem;
  background: #C45C16;
  color: #fff;
  display: flex;
  align-items: center;
}
.govbr-menu-inner {
  max-width: 1140px; margin: 0 auto; padding: .85rem 2rem;
  display: flex; flex-wrap: wrap; justify-content: center;
  gap: .9rem 2.4rem; font-size: .92rem; font-weight: 600;
}
.govbr-step { display: inline-flex; align-items: center; gap: .55rem; color: #fff; }
.govbr-step em {
  font-style: normal; font-size: .78rem; font-weight: 700;
  width: 1.45rem; height: 1.45rem; border-radius: 50%;
  border: 1.5px solid #fff; display: inline-flex;
  align-items: center; justify-content: center;
}
[data-testid="stHorizontalBlock"] {
  align-items: stretch !important;
  gap: 1.2rem !important;
}
[data-testid="stHorizontalBlock"] > div {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
[data-testid="stHorizontalBlock"] > div > div {
  height: 100%;
}
div[data-testid="stVerticalBlockBorderWrapper"] {
  background: var(--govbr-surface);
  border: 1px solid var(--govbr-line) !important;
  border-top: 4px solid var(--govbr-blue) !important;
  border-radius: 12px !important;
  box-shadow: 0 8px 24px rgba(74,34,12,.05);
  padding: 1.15rem 1.2rem 1.25rem !important;
  height: 100%;
  box-sizing: border-box;
}
div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] {
  gap: .55rem !important;
}
.stButton > button { border-radius: 8px; font-weight: 600; font-family: inherit; }
.stButton > button[kind="primary"], .stButton > button[data-testid="stBaseButton-primary"] {
  background: var(--govbr-blue); border-color: var(--govbr-blue);
}
.stButton > button[kind="primary"]:hover, .stButton > button[data-testid="stBaseButton-primary"]:hover {
  background: var(--govbr-blue-dark); border-color: var(--govbr-blue-dark);
}
[data-testid="stMetric"] {
  background: #FFF8F3; border: 1px solid var(--govbr-line); padding: .7rem .9rem; border-radius: 10px;
}
[data-testid="stFileUploader"] { background: transparent; }
[data-testid="stFileUploaderDropzone"] {
  background: #FFF8F3 !important;
  border: 1px dashed #D08A4A !important;
  border-radius: 10px !important;
  padding: 1.15rem 1rem !important;
}
[data-testid="stFileUploaderDropzone"] button {
  font-size: 0 !important;
  border-color: var(--govbr-blue) !important;
  color: var(--govbr-blue) !important;
}
[data-testid="stFileUploaderDropzone"] button::after {
  content: "Escolher arquivo";
  font-size: .88rem;
  font-weight: 600;
}
[data-testid="stFileUploaderDropzoneInstructions"] span { font-size: 0 !important; line-height: 0; }
[data-testid="stFileUploaderDropzoneInstructions"] div:first-child span::after {
  content: "Arraste o arquivo aqui";
  font-size: .95rem;
  font-weight: 600;
  color: var(--govbr-text);
  line-height: 1.3;
}
[data-testid="stFileUploaderDropzoneInstructions"] small,
[data-testid="stFileUploaderDropzoneInstructions"] span small {
  font-size: 0 !important;
}
[data-testid="stFileUploaderDropzoneInstructions"]::after {
  content: "Limite de 512 MB · MP3 e MP4";
  display: block;
  font-size: .8rem;
  color: var(--govbr-muted);
  margin-top: .2rem;
}
[data-testid="stAlert"] {
  background: #F8EDE3 !important;
  color: var(--govbr-text) !important;
  border: 1px solid var(--govbr-line) !important;
  border-radius: 10px !important;
}
[data-testid="stAlert"] svg { fill: var(--govbr-blue) !important; }
[data-testid="stHeading"] { padding-top: 1.6rem !important; }
hr { border-color: var(--govbr-line) !important; }
[data-testid="stElementContainer"]:has(.govbr-top),
.stMarkdown:has(.govbr-top),
[data-testid="stElementContainer"]:has(.govbr-footer),
.stMarkdown:has(.govbr-footer) {
  width: 100% !important;
  max-width: 100% !important;
  margin-left: 0 !important;
  margin-right: 0 !important;
  padding: 0 !important;
}
[data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:not(:has(.govbr-top)):not(:has(.govbr-footer)),
[data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"],
[data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"] > [data-testid="stHeading"],
[data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"] > [data-testid="stExpander"] {
  max-width: 1320px;
  margin-left: auto;
  margin-right: auto;
  padding-left: var(--page-gutter);
  padding-right: var(--page-gutter);
  width: 100%;
  box-sizing: border-box;
}
.govbr-top {
  width: 100%;
  background: var(--govbr-surface);
  margin-bottom: 0;
}
.govbr-footer {
  background: #C2410C;
  color: #fff;
  width: 100%;
  margin: 2.4rem 0 0;
  padding: 0;
}
.govbr-footer-main {
  max-width: 1320px;
  margin: 0 auto;
  padding: 2.1rem var(--page-gutter) 1.8rem;
  display: grid;
  grid-template-columns: 1.6fr repeat(3, minmax(0, 1fr));
  gap: 1.5rem 2rem;
  align-items: start;
}
.govbr-footer-help h3 {
  color: #fff; font-size: 1.15rem; font-weight: 700; margin: 0 0 .4rem;
}
.govbr-footer-help p,
.govbr-footer-item span,
.govbr-footer-item strong,
.govbr-footer-copy {
  color: #FFE8D6;
}
.govbr-footer-help p {
  font-size: .9rem; font-weight: 500; margin: 0; line-height: 1.5; max-width: 22rem;
}
.govbr-footer-item { min-width: 0; padding-left: 1.2rem; border-left: 1px solid rgba(255,255,255,.22); }
.govbr-footer-item span {
  display: block; font-size: .75rem; font-weight: 600; letter-spacing: .04em;
  text-transform: uppercase; margin-bottom: .35rem; opacity: .85;
}
.govbr-footer-item strong {
  display: block; color: #fff; font-size: 1rem; font-weight: 700;
}
.govbr-footer-copy {
  background: #9A3412;
  text-align: center;
  font-size: .8rem; font-weight: 500;
  margin: 0; padding: .9rem 1.2rem 1.1rem;
}
@media (max-width: 768px) {
  :root { --page-gutter: 1.5rem; }
  .govbr-menu { height: auto; }
  .govbr-menu-inner { flex-direction: column; align-items: flex-start; gap: .55rem; padding: .7rem 1.2rem; }
  .govbr-footer-main { grid-template-columns: 1fr; padding: 1.6rem 1.25rem 1.4rem; }
  .govbr-footer-item { padding-left: 0; border-left: 0; padding-top: .8rem; border-top: 1px solid rgba(255,255,255,.22); }
}
</style>
""", unsafe_allow_html=True)


def media_id(upload) -> str:
    # Hash completo para não confundir arquivos com início/fim iguais.
    return hashlib.sha256(upload.getbuffer()).hexdigest()


def safe_stem(name: str) -> str:
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"[^\w .-]", "_", Path(name).stem, flags=re.UNICODE).strip(" .")[:70] or "transcricao"


def clear_result() -> None:
    for key in ("transcription", "editor", "reference"):
        st.session_state.pop(key, None)


def banner_path() -> Path:
    assets = PROJECT_ROOT / "assets"
    for name in ("cabecalho.png", "Pastel Flower Name Desk Strip.png"):
        candidate = assets / name
        if candidate.is_file():
            return candidate
    pngs = sorted(assets.glob("*.png"), key=lambda path: path.stat().st_mtime, reverse=True)
    if pngs:
        return pngs[0]
    raise FileNotFoundError("Nenhuma imagem de cabeçalho encontrada em assets/.")


with st.sidebar:
    st.subheader("Como transcrever")
    model = st.selectbox("Modelo", ["large-v3", "turbo", "medium", "small"],
                         format_func=lambda name: {
                             "large-v3": "Large v3 · priorizar qualidade",
                             "turbo": "Turbo · priorizar velocidade",
                             "medium": "Medium · menos memória",
                             "small": "Small · computadores mais simples",
                         }[name])
    device = st.selectbox("Processamento", ["cpu", "cuda"], format_func=lambda value:
                          "CPU · funciona sem placa NVIDIA" if value == "cpu" else "GPU NVIDIA · requer CUDA")
    st.caption("Idioma: português. Nenhuma chave de API é necessária.")
    context = st.text_area("Assunto da gravação (opcional)", max_chars=300, height=90,
                           placeholder="Reunião de planejamento sobre orçamento público.")
    keywords = st.text_area("Nomes, siglas e termos (um por linha)", max_chars=2000, height=100,
                            placeholder="SEPLAN\nPPA\nCOPLAN")
    with st.expander("Opções avançadas"):
        offline = st.checkbox("Usar somente modelos já baixados", value=False)
        threads = st.number_input("Threads de CPU", min_value=1, max_value=64,
                                  value=min(8, os.cpu_count() or 1))
    st.caption("O primeiro uso baixa o modelo. Depois, ative a opção de modelos já baixados para trabalhar offline.")
    st.caption("As gravações são processadas nesta máquina. O texto fica nesta sessão até você baixar os arquivos.")

_banner_src = f"data:image/png;base64,{base64.b64encode(banner_path().read_bytes()).decode('ascii')}"
st.markdown(f"""
<div class="govbr-top">
  <div class="govbr-banner">
    <div class="govbr-banner-art">
      <img src="{_banner_src}" alt="Fraseando — Transforme áudios e vídeos em texto de forma rápida e fácil.">
    </div>
    <nav class="govbr-menu" aria-label="Etapas">
      <div class="govbr-menu-inner">
        <span class="govbr-step"><em>1</em> Escolher gravação</span>
        <span class="govbr-step"><em>2</em> Transcrever</span>
        <span class="govbr-step"><em>3</em> Revisar e baixar</span>
      </div>
    </nav>
  </div>
</div>
""", unsafe_allow_html=True)
st.title("Sua gravação, em texto.")
st.write("Envie um MP3 ou MP4, transcreva no computador e revise ouvindo o original.")

left, right = st.columns(2, gap="medium")
with left:
    with st.container(border=True):
        st.subheader("1. Escolher gravação")
        st.caption("O arquivo permanece neste computador. Tamanho máximo: 512 MB.")
        uploaded = st.file_uploader("Arquivo MP3 ou MP4", type=["mp3", "mp4"],
                                    on_change=clear_result,
                                    label_visibility="collapsed",
                                    help="Até 512 MB. O limite é de tamanho, não de minutos.")
        if uploaded:
            st.caption(f"{uploaded.name} · {uploaded.size / 1048576:.1f} MB")
            if Path(uploaded.name).suffix.lower() == ".mp4":
                st.video(uploaded)
            else:
                st.audio(uploaded, format="audio/mpeg")

current_file_id = media_id(uploaded) if uploaded else None
if st.session_state.get("file_id") != current_file_id:
    clear_result()
    st.session_state.file_id = current_file_id

with right:
    with st.container(border=True):
        st.subheader("2. Transcrever")
        st.write("O reconhecimento acontece no seu computador, sem cobrança por minuto.")
        st.caption(f"Modelo selecionado: {model} · {'CPU' if device == 'cpu' else 'GPU NVIDIA'}")
        if model == "large-v3" and device == "cpu":
            st.info("Large v3 pode demorar bastante e exige memória. Se faltar memória, selecione Medium ou Small.")
        st.caption("O primeiro download pode levar vários minutos e ocupa alguns GB no caso do Large v3.")
        split_long = st.checkbox(
            "Dividir gravações longas",
            value=True,
            help="Arquivos maiores que o limite são cortados em partes. O texto sai unificado, com os tempos do áudio original.",
        )
        save_audio_parts = st.checkbox(
            "Salvar partes em MP3 no computador",
            value=False,
            disabled=not split_long,
            help="Opcional: somente quando a gravação for dividida. Se desativado, os WAVs temporários são removidos.",
        )
        max_part_minutes = st.number_input(
            "Cada parte, no máximo (minutos)",
            min_value=1, max_value=180, value=20, step=1,
            disabled=not split_long,
            help="Exemplo: 1 hora com limite de 20 minutos vira 3 partes. Áudios menores não são cortados.",
        )
        start = st.button("Iniciar transcrição", type="primary", disabled=uploaded is None,
                           use_container_width=True)

if start and uploaded:
    clear_result()
    try:
        with tempfile.TemporaryDirectory(prefix="fraseado_") as temporary:
            folder = Path(temporary)
            source = folder / f"gravacao{Path(uploaded.name).suffix.lower()}"
            uploaded.seek(0)
            with source.open("wb") as output:
                shutil.copyfileobj(uploaded, output, length=1024 * 1024)
            with st.status("Preparando gravação", expanded=True) as status:
                audio = convert_to_wav(source, folder)
                st.write("Carregando modelo local. No primeiro uso, aguarde o download.")
                engine = get_transcriber(ModelSettings(model=model, device=device,
                                                       cpu_threads=int(threads), offline=offline))
                status.update(label="Transcrevendo no computador")
                bar = st.progress(0.0, text="Aguardando os primeiros trechos…")

                def update(fraction: float, _text: str) -> None:
                    bar.progress(fraction, text=f"Áudio processado: {fraction:.0%}")

                max_part_seconds = float(max_part_minutes) * 60 if split_long else None
                split_directory = (PROJECT_ROOT / "saidas" / f"{safe_stem(uploaded.name)}_{current_file_id[:12]}") if split_long and save_audio_parts else None
                result = transcribe_wav_in_parts(
                    engine, audio, max_part_seconds=max_part_seconds,
                    context=context, keywords=parse_keywords(keywords),
                    on_progress=update, split_directory=split_directory,
                )
                status.update(label="Transcrição concluída", state="complete", expanded=False)
            result.update(file_id=current_file_id, filename=uploaded.name)
            st.session_state.transcription = result
            st.session_state.editor = result["original"]
    except (TranscriptionError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        st.error(str(exc))
    except Exception:
        logging.exception("Falha na transcrição local")
        st.error("Não foi possível concluir. Confira o terminal do Cursor. Se faltar memória, use um modelo menor; se o erro for de CUDA, selecione CPU.")

result = st.session_state.get("transcription")
if result and result["file_id"] == current_file_id:
    st.divider()
    st.subheader("3. Revisar e baixar")
    if not result["original"]:
        st.warning("Nenhuma fala foi identificada. Ouça o arquivo e confira a qualidade da gravação.")
    a, b, c = st.columns(3)
    a.metric("Palavras reconhecidas", len(result["original"].split()))
    b.metric("Reconhecimento", f'{result["elapsed"] / 60:.1f} min')
    c.metric("Modelo utilizado", result["model"])
    st.caption("O tempo acima exclui a preparação da mídia e o download/carregamento do modelo.")
    part_count = result.get("audio_parts", 1)
    if part_count > 1:
        st.info(f"A gravação de {result['duration'] / 60:.1f} min foi transcrita em {part_count} partes.")
        saved = result.get("saved_parts") or []
        if saved:
            folder = Path(saved[0]).parent
            st.caption(f"As partes em MP3 ficaram em {folder} (pasta local, não enviada para a rede).")
    st.text_area("Texto transcrito (editável)", key="editor", height=320)
    text_final = st.session_state.editor
    stem = safe_stem(result["filename"])
    txt, md = st.columns(2)
    txt.download_button("Baixar texto (.txt)", text_final.encode("utf-8"),
                        file_name=f"{stem}_transcricao.txt", mime="text/plain", use_container_width=True)
    md.download_button("Baixar Markdown (.md)", (f"# Transcrição — {stem}\n\n" + text_final).encode("utf-8"),
                       file_name=f"{stem}_transcricao.md", mime="text/markdown", use_container_width=True)
    with st.expander("Trechos com tempo e legendas"):
        st.caption("As legendas usam o texto original. Alterações no editor acima afetam apenas TXT e Markdown.")
        for part in result["parts"]:
            st.write(f'{part["start"] / 60:.2f}–{part["end"] / 60:.2f} min · {part["text"]}')
        srt, vtt = st.columns(2)
        for column, kind in ((srt, "srt"), (vtt, "vtt")):
            column.download_button(f"Baixar legenda (.{kind})", export_subtitles(result["parts"], kind).encode("utf-8"),
                                   file_name=f"{stem}.{kind}", mime="text/vtt" if kind == "vtt" else "text/plain")
    with st.expander("Medir precisão com uma transcrição de referência"):
        st.write("Cole uma transcrição humana conferida do mesmo áudio. A comparação usa o resultado original, antes das suas correções.")
        reference = st.text_area("Transcrição de referência", key="reference", height=140)
        if reference.strip():
            try:
                metrics = calculate_accuracy(reference, result["original"])
                a, b = st.columns(2)
                a.metric("Pontuação 1 − WER", f'{metrics["score"]:.2f}%')
                b.metric("WER", f'{metrics["wer"] * 100:.2f}%')
                if metrics["score"] >= 98:
                    st.success("Meta de 98% atingida nesta comparação.")
                else:
                    st.info("Meta de 98% não atingida nesta comparação.")
                st.caption("Ignora pontuação e maiúsculas; considera palavras e acentos. Não é uma garantia para outras gravações.")
            except ValueError as exc:
                st.warning(str(exc))

st.markdown("""
<div class="govbr-footer">
  <div class="govbr-footer-main">
    <div class="govbr-footer-help">
      <h3>Estamos aqui para ajudar você.</h3>
      <p>Use as etapas da tela e o painel ao lado para transcrever, revisar e baixar.</p>
    </div>
    <div class="govbr-footer-item">
      <span>Uso</span>
      <strong>Transcrição local</strong>
    </div>
    <div class="govbr-footer-item">
      <span>Privacidade</span>
      <strong>Neste computador</strong>
    </div>
    <div class="govbr-footer-item">
      <span>Formatos</span>
      <strong>MP3 e MP4</strong>
    </div>
  </div>
  <p class="govbr-footer-copy">Fraseando · processamento local, sem envio de gravações.</p>
</div>
""", unsafe_allow_html=True)

