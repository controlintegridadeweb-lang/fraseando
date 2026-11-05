# Fraseando

Aplicação Python + Streamlit para transcrever MP3/MP4 em português com Faster Whisper local.

- Mantenha o uso local gratuito, sem exigir APIs pagas ou autenticação.
- Use informações verificáveis. Não prometa 98% de precisão; WER requer referência humana do mesmo áudio.
- Preserve original e texto editado separadamente.
- Não envie gravações, modelos ou saídas para serviços externos.
- Testes: `python iniciar.py --testar`. Os testes não baixam modelos.
- Registre separadamente testes simulados, inferência real e medição de qualidade.
- Não publique o servidor local. Não inclua .venv, .models, gravações, saídas ou segredos em pacotes.
