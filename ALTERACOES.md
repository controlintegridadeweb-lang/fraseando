# Registro das correções — 04/11/2026

## Navegador (`docs/`)

1. Extraiu utilitários verificáveis para `transcription-utils.mjs`, corrigindo a perda de milissegundos no SRT e adicionando VTT.
2. Isolou o modelo Whisper num `transcriber.worker.js` controlado por `worker-client.mjs`; cancelar termina efetivamente o worker, cancela requisições iniciadas e encerra FFmpeg.wasm. Partes que estavam em processamento não são marcadas como concluídas.
3. Verifica nome, tamanho, data e SHA-256 amostral das extremidades antes de permitir a retomada de um arquivo. Não é hash integral; a transcrição já salva em partes permanece no IndexedDB, não o arquivo original.
4. Adicionou botão Cancelar, exportação VTT, mensagens de estado acessíveis e comportamento de falha de gravação/exclusão local sem declarar sucesso indevido.
5. Arquivos de duração desconhecida seguem o fluxo de FFmpeg, evitando decodificar um arquivo longo inteiro sem confirmação da duração. Uploads acima de 512 MB são rejeitados; montagem sem cópia via WORKERFS é priorizada.
6. Corrigiu o descarte de URLs temporárias, do Worker Whisper e de memória WASM do FFmpeg. Falhas de metadados retornam em 12 segundos ou após cancelamento.
7. Atualizou as informações de privacidade e explicou os downloads de bibliotecas/pesos e a diferença entre versão web (Tiny/Base/Small) e local (Large v3 etc.).

## Aplicativo local (`app.py` e `transcription_core.py`)

1. Divide WAVs longos de forma incremental e só mantém uma parte temporária por vez. O WAV original da conversão permanece até o fim e é eliminado pelo diretório temporário.
2. Salvamento permanente das partes MP3 tornou-se opcional, desativado por padrão; quando ativado, o destino inclui identificação do arquivo para reduzir colisões.
3. Adicionou benchmark local de preparação, velocidade e WER condicionado à existência de referência humana. Não promete precisão mínima.

## Testes e validação

- 31 testes Python descobertos: 21 passaram e 10 foram ignorados por dependências/infraestrutura indisponíveis ou opt-in.
- 8 testes Node aprovados para utilitários e protocolo do Worker.
- Teste opcional de uma hora sintética de MP3, com conversão real e três partes WAV, aprovado. Sem execução de modelo ASR nesse teste.
- Testes de browser Playwright presentes, mas bloqueados pelo ambiente (`ERR_BLOCKED_BY_ADMINISTRATOR`), não reportados como aprovados.

A versão web publicada anteriormente não é atualizada pelo download deste ZIP. É necessário atualizar a branch e publicar `docs/` para aplicar as mudanças no site existente. Consulte `VALIDACAO.md` e `README.md` para comandos e limitações.
