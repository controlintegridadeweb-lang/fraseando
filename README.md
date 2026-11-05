# Fraseando — transcrição local e no navegador

**Página pública:** [https://nicollyedu0566-ctrl.github.io/fraseando/](https://nicollyedu0566-ctrl.github.io/fraseando/)

O projeto original foi adaptado para **Faster Whisper local**, sem chave de API, créditos ou cobrança por minuto. Aceita MP3 e MP4 em português. O Cursor edita e executa o código; a interface abre no navegador do seu computador. A página pública transcreve no próprio navegador e não grava o arquivo em servidor.

## Começar no Windows

1. Instale **Python 3.12 de 64 bits** pelo [site oficial](https://www.python.org/downloads/). O projeto aceita Python 3.11–3.13.
2. Extraia o ZIP. No Cursor, use **File → Open Folder** e abra a pasta **fraseando-main**, onde estão este README e iniciar.py.
3. Abra **Terminal → New Terminal** e execute:

    py -3.12 iniciar.py

4. Aguarde a instalação das dependências e abra **http://127.0.0.1:8501**.
5. Escolha o MP3 ou MP4 e clique em **Iniciar transcrição**.

Não é necessário ativar o ambiente virtual, configurar .env ou informar uma chave. O iniciador cria .venv e instala as dependências no primeiro uso. Nas próximas execuções, reutiliza o ambiente enquanto requirements.txt não mudar.

Se o comando py não existir, mas Python estiver instalado e disponível no terminal:

    python iniciar.py

No macOS ou Linux:

    python3 iniciar.py

O backend desta versão acelera por GPU NVIDIA/CUDA. Em macOS e em GPUs AMD/Intel, use CPU. Linux pode exigir o pacote python3-venv da distribuição.

## Modelos e processamento

| Opção | Quando escolher |
| --- | --- |
| Large v3 | Prioridade à qualidade, aceitando maior tempo e consumo de memória |
| Turbo | Prioridade à velocidade, com possível diferença de precisão |
| Medium | Menor consumo de memória que Large v3 |
| Small | Computadores com menos recursos |

O padrão é **Large v3 + CPU int8**, para não depender de uma GPU. Isso não garante que toda máquina terá memória suficiente: se faltar memória, mude para Medium ou Small. O tempo depende de processador, GPU, modelo, configuração e características da gravação.

**GPU NVIDIA** é opcional. Requer hardware compatível e as bibliotecas **CUDA 12/cuBLAS e cuDNN 9** corretamente instaladas. Se houver erro de CUDA, volte para CPU. A detecção de uma GPU pelo diagnóstico não comprova que todas as bibliotecas necessárias à inferência estão instaladas.

O primeiro uso baixa o modelo do Hugging Face, podendo ocupar alguns GB e levar vários minutos. Nenhuma gravação é enviada para esse download. Os pesos não vêm no ZIP.

Para baixar previamente o Large v3:

    py -3.12 iniciar.py --baixar-modelo large-v3

Depois, em **Opções avançadas**, marque **Usar somente modelos já baixados**. Preserve a pasta .models, pois ela contém os modelos. O modo offline impede a busca do modelo na internet; não exige uma conexão com serviços de transcrição.

## Revisão e exportação

- TXT e Markdown usam o texto corrigido no editor.
- SRT e VTT usam os segmentos e tempos do reconhecimento original, preservando milissegundos. Editar o texto corrido não modifica essas legendas.
- O áudio original pode ser reproduzido na própria tela.
- Nomes, siglas e termos são pistas para o modelo; não garantem a grafia correta.
- A barra mostra a posição processada no áudio. Não é um percentual de precisão nem uma previsão linear do tempo restante.
- O tempo de reconhecimento apresentado exclui download/carregamento do modelo e preparo da mídia.

Os arquivos temporários de conversão são removidos ao terminar. O aplicativo não mantém histórico ou autosave. Baixe o texto antes de fechar ou atualizar a sessão. O original escolhido permanece no seu computador.

## Precisão

Não há garantia de 98% para qualquer gravação. A seção de avaliação compara o **texto original produzido pelo modelo** com uma referência humana do mesmo áudio. Usa distância de edição entre palavras (WER), ignorando maiúsculas e pontuação e considerando acentos. A pontuação é max(0, 100 × (1 − WER)).

Correções no editor não aumentam artificialmente a pontuação. Silêncios, ruído, vozes sobrepostas e nomes pouco comuns podem causar omissões, repetições ou palavras inexistentes. Esta versão não identifica pessoas que falam.

## Cursor: tarefas e depuração

O pacote inclui tarefas, configuração de depuração e regras do projeto.

- Pela paleta de comandos, procure **Tasks: Run Task** e selecione **Fraseando: executar**, **instalar**, **testar**, **diagnóstico** ou **baixar Large v3**.
- Instale as extensões Python e Python Debugger sugeridas pelo editor se quiser depurar.
- Após a primeira instalação, selecione o interpretador Python da pasta .venv.
- Use a configuração **Fraseando: depurar** no painel Run and Debug.

O comando no terminal é suficiente para utilizar a aplicação. O assistente de IA do Cursor não é necessário para transcrever.

## Desenvolvimento e testes

    py -3.12 iniciar.py --testar
    py -3.12 iniciar.py --diagnostico

Sem usar o iniciador, com um ambiente virtual já configurado:

    python -m pip install -r requirements.txt
    python -m streamlit run app.py
    python -m unittest discover -s tests -v

Os testes de software não baixam modelos. Exercitam conversão real de mídia, exportação, WER, interface e o contrato do motor com simulação. A validação de reconhecimento real e de qualidade precisa de um modelo baixado e de gravações de referência. Veja VALIDACAO.md para o que foi executado neste pacote.

O cache mantém um modelo por configuração e libera o anterior antes de carregar outro. Mídia é preparada em WAV PCM mono 16 kHz, sem a recompressão MP3 intermediária do fluxo anterior. Ao escolher dividir, apenas **uma parte WAV temporária** é criada de cada vez e removida no final. A gravação pode ser salva em partes MP3 somente quando a opção correspondente for marcada; o padrão é **não manter** esses arquivos. O Faster Whisper segmenta o reconhecimento internamente; não existe limite de 25 MB imposto por uma API.


## Validação de desempenho e precisão com gravações reais

Há um benchmark local reproduzível, sem enviar o áudio para servidores. Para medir somente conversão e memória de um arquivo (sem modelo), execute:

    python scripts/benchmark.py caminho/para/reuniao.mp3 --preparo-apenas --saida resultado.json

Para medir reconhecimento real com um modelo **já baixado**, usando a referência humana do **mesmo áudio**:

    python scripts/benchmark.py caminho/para/reuniao.mp3 --modelo large-v3 --referencia referencia.txt --saida resultado.json

O relatório JSON inclui duração, tempo real de reconhecimento, fator de tempo real, consumo máximo de memória do processo quando a plataforma disponibiliza essa informação e WER quando houver referência. Para permitir o download inicial de modelos, use explicitamente `--permitir-download-modelo`. O benchmark não registra o texto transcrito e não assegura qualquer porcentagem de precisão. A pontuação só vale para a gravação testada. O campo `ru_maxrss` é um pico do processo, incluindo bibliotecas e modelo, e possui unidades diferentes no Linux/macOS.

Um teste opcional verifica **1 hora sintética** de MP3, conversão e divisão (sem Whisper):

    FRASEADO_STRESS=1 python -m unittest tests.test_long_audio -v

Para executar o navegador com motor simulado, é preciso Playwright, Chromium e acesso HTTP a `127.0.0.1`:

    FRASEADO_BROWSER_E2E=1 python -m unittest tests.test_browser -v

Teste do núcleo web sem navegador, somente Node.js 22+ (sem npm install):

    node --test tests/browser_utils.test.mjs

Esses testes não substituem uma validação real do Large v3 em gravações portuguesas de uma hora em equipamentos de referência. A comparação de precisão exige transcrição humana e um modelo disponível. Consulte `VALIDACAO.md` para saber quais testes foram executados efetivamente nesta revisão.

## Solução de problemas

| Situação | Ação |
| --- | --- |
| Não reconhece py/python | Instale Python 3.12 de 64 bits e reabra o terminal |
| Instalação com Python 3.14+ | Execute explicitamente com py -3.12 |
| Memória insuficiente ou processo encerrado | Escolha Medium/Small e feche programas pesados |
| Erro de CUDA/cuDNN | Selecione CPU; configure a GPU separadamente |
| Modelo indisponível offline | Desmarque o modo offline, baixe o modelo e tente novamente |
| Falha no download | Confira internet, espaço em disco, firewall e acesso ao Hugging Face |
| Proxy SOCKS exige socksio | Execute .venv\Scripts\python.exe -m pip install socksio |
| Vídeo sem áudio ou arquivo corrompido | Confira a reprodução em um player e exporte novamente |
| Porta 8501 ocupada | Feche a instância anterior com Ctrl+C ou use python -m streamlit run app.py --server.port 8502 |

O serviço escuta em **127.0.0.1**. Esta configuração é para uso pessoal local. Não foi preparada para hospedagem pública.

O código da versão web está em `docs/` e pode ser publicado no GitHub Pages. Para testar localmente sem publicar, execute `python -m http.server 8000 --bind 127.0.0.1 --directory docs` na raiz do projeto e abra `http://127.0.0.1:8000`. A primeira execução precisa de internet para baixar o modelo e o FFmpeg.wasm. A página já existente é [https://nicollyedu0566-ctrl.github.io/fraseando/](https://nicollyedu0566-ctrl.github.io/fraseando/); **as correções deste ZIP só aparecerão lá após atualizar o repositório e publicar**.

A versão web executa Whisper Tiny/Base/Small em um **Web Worker**, sem enviar a gravação a serviço de transcrição. O botão **Cancelar** termina o reconhecimento ou recorte em andamento. Partes já concluídas são salvas como texto no IndexedDB e podem ser retomadas selecionando o **mesmo arquivo original**; nenhuma parte em andamento é considerada concluída. A identificação para retomada usa nome, tamanho, data e SHA-256 das extremidades do arquivo, sem precisar ler a gravação inteira. Não é verificação criptográfica integral de todo o arquivo.

Na interface web, TXT e Markdown usam o texto editado, enquanto SRT e VTT usam os trechos originais com timestamps em milissegundos. Áudios grandes dependem de FFmpeg.wasm e memória disponível; o limite de entrada é de **512 MB**, mas esse limite não é garantia de que todo dispositivo consiga executar. O navegador baixa componentes de **jsDelivr** e pesos de modelo via serviços de terceiros, embora o áudio seja processado no próprio aparelho. O armazenamento do navegador pode manter texto parcial e metadados até concluir ou clicar em **Descartar progresso**. Sem HTTPS/localhost, a retomada pode ficar indisponível.

**As capacidades não são idênticas:** somente a versão Python oferece Large v3, Turbo, avaliação de WER na interface e configuração CPU/CUDA. O navegador continua em Tiny/Base/Small devido às restrições de RAM e execução WebAssembly. Não há promessa de 98% de precisão ou funcionamento em todos os aparelhos.

## Docker opcional (CPU)

Este caminho não é necessário para usar no Cursor. Os comandos abaixo preservam os modelos em um volume e expõem a porta apenas no computador local:

    docker build -t fraseado .
    docker run --rm -p 127.0.0.1:8501:8501 -v fraseado-modelos:/app/.models fraseado

Docker não foi executado na validação deste ambiente.

## Referências técnicas

- [Faster Whisper: execução local, CPU/GPU e requisitos](https://github.com/SYSTRAN/faster-whisper)
- [Whisper: modelos e limitações](https://github.com/openai/whisper)
- [Streamlit](https://docs.streamlit.io/)
- [Regras do Cursor](https://cursor.com/docs/rules)

