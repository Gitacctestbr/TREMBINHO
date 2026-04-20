# TREMBINHO — Segundo Cérebro SDR
**Assistente conversacional local que gerencia pipeline Notion via linguagem natural (PT-BR).**

---

## STACK & CREDENCIAIS

- **LLM:** Ollama + Qwen 2.5 14B (temperature=0.3, num_ctx=8192)
- **Banco:** Notion API (database "trembobase")
- **Chat:** Telegram (Long Polling)
- **Python:** ollama, notion-client, requests, python-dotenv, dateparser

```
.env (NÃO commitar):
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
NOTION_API_KEY, NOTION_DATABASE_ID
GEMINI_API_KEY, GROQ_API_KEY (opcionais)
```

---

## ARQUIVOS PRINCIPAIS

| Arquivo | Função |
|---------|--------|
| `agente.py` | **MOTOR CRÍTICO.** processar_mensagem() → Qwen → tool_calls. Blindagem N3 (regex fallback). |
| `main.py` | REPL terminal interativo |
| `listener_main.py` | Bot Telegram oficial (auto-reinício, log estruturado) |
| `tray_app.py` | App de bandeja Windows (liga/desliga bot, atalhos) |
| `ponte_telegram.py` | Orquestrador: comandos, typing, memória, particionamento |
| `agendador.py` | Notificações agendadas (JSON, thread daemon 30s, parsing PT-BR) |
| `datas.py` | Parser de datas PT-BR (5 camadas) |
| `memoria.py` | Histórico por chat_id (janela 20 msgs, thread-safe) |
| `notion.py` | CRUD Notion (retorna list[dict]) |
| `notificador.py` | Envio Telegram + retry em disco |
| `verificar_pendencias.py` | Relatório diário "BOM DIA CHEFE" (cron) |

---

## FUNCIONALIDADES IMPLEMENTADAS

**Pipeline Notion**
- `"anota lead João para segunda às 10h"` → salva
- `"quais tarefas tenho essa semana?"` → lista com filtros
- `"marca ABC como em andamento"` → edita
- `"remove a tarefa de...?"` → exclui
- Filtros: tipo (Lead/Tarefa/Nota/Ideia), status (Aberto/Em andamento/Concluído), data

**Notificações**
- `"lembrete em 2h: enviar proposta"` → agenda
- Aceita: "em 5min", "daqui 1h30", "às 14h30", "amanhã às 9h"
- `/notificacao` → lista pendentes
- Persistência JSON + boot recovery + thread check 30s

**Terminal & Telegram**
- Terminal: REPL (main.py)
- Bot: Long Polling + auto-reinício (listener_main.py)
- Comandos: `/start`, `/help`, `/reset`, `/status`, `/notificacao`
- Typing indicator, particionamento >4096 chars, memória por chat_id

**Outros**
- Tray app (bandeja Windows, auto-startup, atalhos)
- Relatório diário (manha|tarde|fim)
- HTML+emojis (👤 Lead, 📞 Tarefa, 📝 Nota, 💡 Ideia; 🟢 Aberto, 🟡 Em andamento, ✅ Concluído)

---

## FERRAMENTAS (Function Calling)

O Qwen reconhece estas funções:

| Função | Parâmetros | Uso |
|--------|-----------|-----|
| `ferramenta_salvar_notion` | nome, tipo, status, data, descricao | Criar |
| `ferramenta_listar_notion` | tipo?, status?, data_inicio?, data_fim? | Buscar |
| `ferramenta_editar_notion` | nome_busca, campo, novo_valor | Atualizar |
| `ferramenta_excluir_notion` | nome_busca | Deletar |
| `ferramenta_agendar_notificacao` | tempo, contexto | Agendar lembrete |
| `ferramenta_listar_notificacoes` | (nenhum) | Ver lembretes |
| `ferramenta_cancelar_notificacao` | id_ou_contexto | Remover lembrete |
| `ferramenta_editar_notificacao` | id, novo_tempo?, novo_contexto? | Editar lembrete |

---

## CAMPOS DO NOTION

| Campo | Tipo | Valores |
|-------|------|--------|
| Nome | title | texto livre |
| Tipo | select | Lead / Tarefa / Nota / Ideia |
| Status | select | Aberto / Em andamento / Concluído |
| Data | date | YYYY-MM-DD |
| Descrição | rich_text | texto livre |

---

## COMO RODAR

```powershell
# Terminal
python main.py

# Bot Telegram (produção)
python listener_main.py

# Tray app (Windows)
python tray_app.py

# Relatório (cron)
python verificar_pendencias.py --horario manha|tarde|fim

# Testes
python -m trembinho.datas
python -m trembinho.memoria
```

---

## ESTADO (Abril 2026)

**✅ Pronto:** Terminal, Bot Telegram, Notion CRUD, Notificações, Tray, Relatório, HTML+emojis, Blindagem N3/N4, Datas PT-BR, Memória, Retry  
**⚠️ Dívidas:** tray dispara testar_ponte.py (devia ser listener_main.py), sem instalador .exe, Qwen às vezes não infere status, áudio/foto ignorados

---

## REGRAS INEGOCIÁVEIS

1. **1 arquivo por vez** — edite, entregue, aguarde OK
2. **Código completo** — nunca `# resto permanece igual`
3. **Leia antes** — especialmente `agente.py` (não quebre Blindagem N3)
4. **Zero regressão** — todo change preserva validado
5. **Debug visível** — flag `[DEBUG]` ou `[BLINDAGEM NX]` desligável
6. **Validar com prints** — terminal e/ou Telegram antes de "done"
7. **PT-BR claro** — traduza jargão, explique em linguagem acessível

---

## MÓDULOS CRÍTICOS

**agente.py:** `processar_mensagem(texto, historico, auto_confirmar_gravacao)` é coração. Blindagem N3 → regex fallback se Qwen falha. DEBUG_EXTRACAO=False produção.

**notion.py:** `listar_itens_no_notion()` retorna `list[dict]` (não string crua). `criar_pagina_no_notion(..., auto_confirmar=True)` pra Telegram.

**agendador.py:** Parsing 5-camadas (min → h → abs → datas.py). JSON persistência. Thread 30s. `DEBUG_AGENDADOR=True`.

**ponte_telegram.py:** Intercepta `/cmd`, typing 4s renovado, particiona >4096, memória chat_id.

**listener_main.py:** Auto-restart crash counter (max 10, reset >300s). Log console+arquivo.

**tray_app.py:** Ícone verde/cinza, menu liga/desliga, Registry startup, atalho Desktop.

**verificar_pendencias.py:** `--horario manha|tarde|fim` → copy SDR narrativo.
