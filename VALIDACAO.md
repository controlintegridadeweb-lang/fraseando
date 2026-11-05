# Validação da revisão — 04/11/2026

## Ambiente disponível

Linux x86_64, Python 3.13.5, Node.js 22.16.0, FFmpeg via `imageio-ffmpeg` e RapidFuzz instalados. Sem acesso à rede de pacotes Python, com a navegação de Chromium bloqueada por política do ambiente. Nesta revisão não havia Streamlit, Faster Whisper nem pesos de modelos instalados. Por isso não declaramos uma execução real de reconhecimento nesta revisão.

## Testes efetivamente executados nesta revisão

- `python -m unittest discover -s tests -v`: **31 testes descobertos; 21 aprovados e 10 ignorados**, pois faltavam dependências e infraestrutura de browser, e o estresse foi configurado para ser opcional.
- `node --test tests/*.test.mjs`: **8 aprovados**; inclui 1 ms, arredondamento de SRT/VTT, metadados e impressão amostral do arquivo de retomada, limite de partes, execução/cancelamento e falhas de worker.
- `FRASEADO_STRESS=1 python -m unittest tests.test_long_audio -v`: **2 aprovados**, incluindo geração de um MP3 **sintético com 60 minutos**, conversão real para PCM e três partes WAV temporárias sequenciais. O reconhecimento foi simulado; isso testa o pipeline de mídia e seu comportamento em disco, não desempenho/qualidade do modelo.
- `python -m compileall -q app.py iniciar.py transcription_core.py scripts tests`, `node --check docs/app.js`, `node --check docs/transcriber.worker.js`: sintaxe aprovada.
- MP3 e MP4 reais de curta duração foram convertidos e validados com FFmpeg pelo teste de mídia. Um vídeo sem áudio e arquivos inválidos foram rejeitados.

## Testes disponíveis, mas não executados neste ambiente

- 4 casos de Streamlit em `tests/test_app.py` (dependência não instalada).
- 3 casos que dependem de `faster_whisper`/PyAV em `tests/test_core.py` (dependência não instalada).
- 2 casos Playwright de página, upload, conclusão, downloads, cancelamento e retomada em `tests/test_browser.py`. O Chromium foi iniciado, mas seu acesso a `http://127.0.0.1` e `file://` foi bloqueado com `ERR_BLOCKED_BY_ADMINISTRATOR`. Esses testes permanecem opt-in (`FRASEADO_BROWSER_E2E=1`).
- Transcrição real com Large v3/Turbo/Medium/Small, download dos modelos, desempenho em CPU/GPU NVIDIA, compatibilidade macOS/Windows e navegação móvel. Não há benchmark real desses itens nesta revisão.
- Medição de WER com referência humana do usuário. **Não é possível certificar 98% de precisão** sem um conjunto de gravações e transcrições humanas representativas.

O `VALIDACAO.md` que vinha no ZIP original relatava 20 testes, inicialização de Streamlit e uma inferência Tiny em outro ambiente em 03/11/2026. Isso é histórico da versão anterior e **não** deve ser tratado como prova de execução da versão modificada.

## Comandos para reprodução

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
node --test tests/browser_utils.test.mjs
FRASEADO_STRESS=1 python -m unittest tests.test_long_audio -v
FRASEADO_BROWSER_E2E=1 python -m unittest tests.test_browser -v  # requer Playwright e Chromium
python scripts/benchmark.py gravacao.mp3 --preparo-apenas --saida medicao.json
python scripts/benchmark.py gravacao.mp3 --modelo large-v3 --referencia humana.txt --saida medicao.json
```

O teste web com Worker simulado não verifica a inferência real da biblioteca Transformers.js nem o download de FFmpeg.wasm. O teste sintético de 1 hora não valida a acurácia, a rapidez do reconhecimento ou o consumo de memória dos modelos. Para isso, use `scripts/benchmark.py` com arquivo real e modelo disponível.

## Correções contempladas

- Timings SRT e VTT corrigidos para milissegundos; validação de intervalos e sequências sem linhas vazias.
- Reconhecimento do navegador isolado em Web Worker e cancelável mediante terminação; FFmpeg.wasm também é encerrado, sem tratar parte interrompida como concluída.
- Retomada só permite arquivo com metadados e impressão SHA-256 amostral correspondentes, impedindo a retomada acidental de um arquivo diferente com nome/tamanho iguais.
- Saldo do processamento armazenado no IndexedDB como texto e metadados, com descarte explícito; áudio não é gravado no IndexedDB.
- Conversão local preserva uma única parte temporária em WAV por vez; partes MP3 persistentes são opt-in.
- Limite e formato de upload tratados antes de iniciar; foco nas diferenças funcionais entre o navegador e o aplicativo local sem simular capacidade Large v3 no navegador.
- Benchmark local reprodutível disponível para preparo, tempo de reconhecimento, fator de tempo real e WER (somente com referência humana).
- Declarações de privacidade e restrições atualizadas; cópias do site em produção **não são alteradas** pelo ZIP.
