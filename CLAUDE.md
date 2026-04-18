# TREMBINHO — Segundo Cérebro SDR
## Briefing para Claude Code

---

## IDENTIDADE DO PROJETO

**Nome:** Trembinho  
**Dono:** SDR da V4 Company (assessoria de marketing digital / performance)  
**Missão:** Assistente conversacional que gerencia pipeline de prospecção no Notion via linguagem natural (PT-BR), acessível por terminal local e Telegram bidirecional.  
**Ambiente:** 100% local no Windows (VS Code + PowerShell), exceto chamadas a APIs externas.  
**Hardware:** Ryzen 5 5500, 32GB RAM, 16GB VRAM.

---

## STACK

- **LLM local:** Ollama rodando `qwen2.5:14b` (temperature=0.3, num_ctx=8192)
- **Notion API:** versão `2025-09-03` via `notion-client` — database "trembobase"
- **Telegram:** Long Polling via `requests` puro (sem python-telegram-bot)
- **Python 3**, `ollama`, `notion-client`, `requests`, `python-dotenv`, `dateparser`
- **Repositório:** GitHub (privado)

### Variáveis de ambiente (.env na raiz)
```
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
NOTION_API_KEY
NOTION_DATABASE_ID
GEMINI_API_KEY      # presente mas não usada ativamente
GROQ_API_KEY        # será usada no Sprint 5 (voice notes)
```

---

## ESTRUTURA DE ARQUIVOS

```
trembinho/                  ← pacote principal
  __init__.py
  agente.py                 ← MOTOR PRINCIPAL. Nunca quebre este arquivo.
  personalidade.py          ← system prompt v6 (Malandragem Semântica)
  notion.py                 ← integração Notion (novo contrato: list[dict])
  datas.py                  ← interpretador de datas PT-BR (5 camadas)
  memoria.py                ← histórico por chat_id (thread-safe)
  config.py                 ← carregamento do .env
  notificador.py            ← envio Telegram com fila de retry em disco
  ponte_telegram.py         ← orquestrador listener ↔ motor ↔ memória
  telegram_listener.py      ← Long Polling, firewall de chat_id, offset em disco

main.py                     ← entry point modo terminal
testar_ponte.py             ← entry point TEMPORÁRIO do bot bidirecional
verificar_pendencias.py     ← relatório diário (cron) "BOM DIA CHEFE"

.env                        ← NÃO commitar nunca
telegram_offset.txt         ← NÃO commitar (controle interno do listener)
fila_retry_telegram.txt     ← NÃO commitar (fila de retry de mensagens)
CLAUDE.md                   ← este arquivo
```

---

## ARQUITETURA — FLUXO PRINCIPAL

```
Telegram (texto) 
  → telegram_listener.py   (recebe, valida chat_id, chama callback)
  → ponte_telegram.py      (comandos especiais, typing, memória)
  → agente.py              (enriquece data → Ollama Qwen → tool calls → Blindagem N3)
  → notion.py              (cria ou lista no Notion)
  → ponte_telegram.py      (formata resposta HTML, envia via notificador)
  → Telegram (resposta formatada)
```

---

## MÓDULOS CRÍTICOS — LEIA ANTES DE EDITAR

### `agente.py` — Motor puro
- `processar_mensagem(texto, historico, auto_confirmar_gravacao)` é o coração do sistema.
- **Blindagem Nível 3:** quando Qwen falha nos campos, extratores heurísticos (regex) capturam `nome`, `data` e `descricao` direto da mensagem crua. Funções: `_extrair_nome_heuristico()`, `_extrair_descricao_heuristica()`, `_extrair_data_forcada_da_mensagem()`.
- **Formatação de saída:** `_formatar_listagem()` (completa, com cabeçalho 🎯), `_formatar_listagem_compacta()` (só bullets, pra `verificar_pendencias.py`), `_formatar_confirmacao_salvamento()`.
- `DEBUG_EXTRACAO = False` em produção. Manter False salvo indicação contrária.
- **NUNCA** remova ou simplifique a Blindagem N3 sem autorização explícita.

### `notion.py` — Novo contrato (Passo 5.6)
- `listar_itens_no_notion()` retorna `list[dict]` com chaves `{nome, tipo, status, data, descricao}` ou `{"erro": "..."}`.
- `criar_pagina_no_notion()` retorna `True/False`. Parâmetro `auto_confirmar=True` pula o [Y/n] do terminal (usado pelo Telegram).
- **Não existe mais string crua de listagem.** A função `listar_itens_formatado_legado()` é deprecated — não referencie ela em código novo.

### `personalidade.py` — System prompt v6
- Contém "Malandragem Semântica v6" com few-shots ensinando o Qwen a extrair `nome`, `tipo`, `data` e `descricao` da mensagem em PT-BR.
- Tem seção explícita "CAMPO descricao — DESCRIÇÃO LIVRE" com 5 exemplos. Não remova.

### `datas.py` — Interpretador determinístico
- 5 camadas: triviais (hoje/amanhã) → regex DD/MM → dias da semana → "daqui a X" → dateparser.
- 17/18 testes unitários passando. Rode com `python -m trembinho.datas` pra verificar.

### `memoria.py` — Histórico por chat_id
- Janela deslizante de 20 mensagens + system prompt preservado.
- Thread-safe via `threading.Lock`.
- 5/5 testes passando. Rode com `python -m trembinho.memoria`.

---

## CAMPOS DO NOTION (database "trembobase")

| Campo | Tipo | Valores válidos |
|---|---|---|
| Nome | title | texto livre |
| Tipo | select | Lead / Tarefa / Nota / Ideia |
| Status | select | Aberto / Em andamento / Concluído |
| Data | date | ISO 8601 (YYYY-MM-DD ou YYYY-MM-DDTHH:MM:00) |
| Descrição | rich_text | texto livre |

---

## ESTADO ATUAL (Abril 2026)

### ✅ Funcionando e validado
- Modo terminal (`python main.py`)
- Bot Telegram bidirecional (`python testar_ponte.py`)
- Listagens com cards formatados (bullet denso com emojis)
- Gravação com Blindagem N3 (nome, data, descrição)
- Relatório diário (`python verificar_pendencias.py --horario manha|tarde|fim`)
- Memória de conversa por chat_id
- Comandos especiais `/start`, `/help`, `/reset`, `/status`
- Push notifications com retry em disco

### ⚠️ Dívidas técnicas abertas
- `testar_ponte.py` é gambiarra temporária — será substituído por `listener_main.py`
- Bot morre quando PowerShell fecha (sem deploy automatizado ainda)
- Qwen nem sempre infere `status=Aberto` em perguntas de listagem
- Mensagens não-texto no Telegram (áudio, foto, sticker) são ignoradas silenciosamente

---

### Fora de escopo (não implementar sem autorização)
- Persistência de histórico em SQLite
- TTS (text-to-speech)
- WhatsApp / Discord
- Dashboard web
- Google Calendar

---

## REGRAS DE TRABALHO (INEGOCIÁVEIS)

1. **1 arquivo por vez.** Nunca edite múltiplos arquivos de uma vez sem autorização explícita. Entregue 1 arquivo → espere confirmação → avance.

2. **Código completo sempre.** Ao fornecer código, entregue o arquivo `.py` INTEIRO e ATUALIZADO. É proibido usar `# resto do código permanece igual` ou pseudocódigo.

3. **Analise antes de codar.** Leia os arquivos relevantes ANTES de escrever qualquer linha. Especialmente `agente.py` — não quebre a Blindagem N3.

4. **Não quebre o que funciona.** Zero regressão. Toda mudança preserva o que já está validado.

5. **Debug visível.** Qualquer heurística nova deve ter log `[DEBUG]` ou `[BLINDAGEM NX]` desligável por flag.

6. **Validar com evidências reais.** Antes de marcar algo como concluído, pedir print do terminal e/ou Telegram.

7. **Português claro.** O dono do projeto não é programador. Traduza jargão técnico. Explique decisões em linguagem acessível antes de escrever código.

---

## COMO RODAR

```powershell
# Modo terminal
python main.py

# Bot Telegram bidirecional (temporário)
python testar_ponte.py

# Relatório diário manual
python verificar_pendencias.py --horario manha
python verificar_pendencias.py --horario tarde
python verificar_pendencias.py --horario fim

# Testes unitários
python -m trembinho.datas
python -m trembinho.memoria
```

---

## PADRÃO DE FORMATAÇÃO DO TELEGRAM

As respostas usam **HTML** (não Markdown). Parse mode: `HTML`.

```
🎯 <b>Tarefas • Aberto • hoje</b>

• 📞 Ligar para Rafael — 📅 18/abr 10:00 🟢
• 📞 Mandar proposta Gustavo — 📅 18/abr 🟢

<i>2 itens</i>
```

Emojis por tipo: 👤 Lead | 📞 Tarefa | 📝 Nota | 💡 Ideia  
Emojis por status: 🟢 Aberto | 🟡 Em andamento | ✅ Concluído