# TREMBINHO — Handoff de Projeto

> **Documento de transição entre conversas.**  
> Contém: (1) relatório estratégico do que foi construído, (2) roadmap do que falta, (3) prompt de kickoff pronto para colar em uma nova conversa.

---

## PARTE 1 — Relatório Estratégico

### O que é o Trembinho

Um "Segundo Cérebro" local em Python para a rotina de SDR (Sales Development Representative) da V4 Company. É um agente inteligente operado via terminal no VS Code que interpreta comandos em linguagem natural e executa ações autônomas em ferramentas do dia a dia comercial.

### Visão do produto final

- **Ferramenta 1 — Notion ("cofre visual")**: criar e gerenciar uma tabela "Caixa de Entrada" para salvar leads, tarefas, notas e ideias.
- **Ferramenta 2 — Google Calendar ("orquestrador de tempo")**: criar reuniões cruzando a agenda do SDR com a do Closer responsável. Regra de negócio crítica: a disponibilidade que manda é a do Closer, não a do SDR — SDRs podem ter várias reuniões sobrepostas desde que cada uma tenha um Closer diferente e livre.
- **Cérebro — Gemini 2.5 Flash**: interpretação de linguagem natural + Function Calling (o agente decide sozinho quando chamar Notion ou Calendar).
- **Padrão de nomeação de eventos**: `V4 | Nome do Closer & Nome do Lead - Empresa`.
- **Double-check humano**: antes de qualquer escrita em Notion ou Calendar, terminal imprime resumo e pede `[Y/n]`.
- **Fila de retry**: falhas de rede/API salvam tentativa em `.txt` local para retry posterior, sem perder informação nem travar o código.
- **Sem WhatsApp nesta fase.**

### Estado atual do projeto (fim da conversa 1)

**✅ Fase 1 — Ambiente e fundação [CONCLUÍDA]**
- Pasta `trembinho` no Desktop
- Ambiente virtual (`venv`) ativo
- Estrutura modular pronta (`main.py` + pacote `trembinho/` com `config.py`, `personalidade.py`, `agente.py`, `notion.py`)
- `.env` com chaves protegidas, `.gitignore` configurado
- Bibliotecas instaladas: `google-genai`, `python-dotenv`, `notion-client` (versão 5+)

**✅ Fase 2 — Chat com IA [CONCLUÍDA]**
- Conexão com Gemini 2.5 Flash funcionando
- Chat interativo com memória de sessão (`cliente.chats.create`)
- Personalidade "Trembinho" carregada como system instruction (tom SDR V4, respostas curtas, linguagem comercial BR)
- Loop de conversa no terminal com comandos de saída (`sair`, `exit`, `quit`, `fechar`)
- Tratamento básico de erros no loop
- Bug "client has been closed" resolvido com context manager (`with genai.Client(...)`)

**✅ Fase 3 — Conexão com Notion [CONCLUÍDA]**
- Integração "Trembinho" criada no Notion
- Database `trembobase` criado com 5 colunas: Nome (title), Tipo (select), Status (select), Date (date), Descrição (rich_text)
- Integração conectada (autorizada) ao database
- Código adaptado para a API Notion versão 2025-09-03 (databases foram separados em "database" + "data_source")
- Função `obter_data_source_id()` funciona e retorna o ID correto
- Função `testar_conexao()` lista corretamente as 5 colunas no terminal

**⏳ Fase 4 em diante — PENDENTES** (ver roadmap abaixo)

### Arquivos do projeto e responsabilidades

```
trembinho/                          (raiz do projeto, no Desktop)
├── venv/                           (ambiente virtual, não mexer)
├── .env                            (chaves de API — NUNCA subir pro Git)
├── .gitignore                      (protege .env, venv, __pycache__, fila_retry.txt)
├── main.py                         (recepcionista — 35 linhas, só orquestra)
│
└── trembinho/                      (pacote Python — os "departamentos")
    ├── __init__.py                 (marca a pasta como pacote)
    ├── config.py                   (lê .env, retorna dict de chaves)
    ├── personalidade.py            (system prompt do agente, texto grande)
    ├── agente.py                   (cria cliente Gemini, chat, loop)
    └── notion.py                   (integração Notion: cliente + data_source + teste)
```

### Decisões técnicas importantes (e por que foram tomadas)

1. **Modelo: `gemini-2.5-flash`** — o `gemini-2.0-flash` foi descontinuado em março/2026. O 2.5 Flash tem tier gratuito vigente (10 RPM, 250 RPD), suficiente pro caso de uso.

2. **Biblioteca: `google-genai`** (não `google-generativeai`) — a antiga foi oficialmente descontinuada pelo Google. A nova é `from google import genai`.

3. **Context manager obrigatório para o cliente Gemini** — usar `with genai.Client(...) as cliente:` em vez de criar e retornar de dentro de função. Isso resolve o bug "Cannot send a request, as the client has been closed" documentado na issue #1763 do `python-genai`.

4. **Notion API 2025-09-03** — a API separou "database" (container) e "data_source" (tabela com colunas). O código chama `databases.retrieve()` → extrai `data_sources[0]["id"]` → chama `data_sources.retrieve()` pra pegar o schema. Operações de escrita daqui pra frente vão usar `data_source_id`, não `database_id`.

5. **Estrutura modular antes de crescer** — optamos por criar o pacote `trembinho/` com módulos separados enquanto o projeto era pequeno, para não virar bagunça quando adicionarmos Calendar, function calling, retry queue.

6. **Temperatura do Gemini: 0.7** — equilíbrio entre respostas determinísticas e criativas.

7. **Caminhos relativos com `pathlib`** — todos os arquivos usam `Path(__file__).parent` para funcionar independente de onde o script é executado.

### O perfil do usuário (fundamental para a próxima IA saber)

- **Iniciante em programação**, entusiasta, foco em eficiência.
- Trabalha como SDR na V4 Company (assessoria de marketing digital focada em performance).
- Windows, VS Code, PowerShell.
- Máquina potente: AMD Ryzen 5 5500, 32GB RAM, GPU AMD Radeon 16GB VRAM. Pode rodar processamento pesado local (vetoriais, LLMs locais) sem problema no futuro.
- **Não sabe editar pedaços de código** — precisa de arquivo completo sempre para Ctrl+A / Ctrl+V.
- Python 3.14 instalado (detalhe importante: algumas libs têm bugs específicos nessa versão).
- Python localizado em `C:\Users\DESKTOP\AppData\Local\Programs\Python\Python314\`.

### Regras de ouro que FUNCIONARAM (manter)

1. **Um passo por vez, sempre.** Explicar → dar código → testar → esperar "funcionou" → avançar.
2. **Arquivo `.py` completo, sempre.** Nunca usar `// resto do código aqui` ou similar.
3. **`venv` explícito em todos os comandos.** Sempre lembrar de ativar antes de `pip install` ou rodar scripts.
4. **`pathlib` / `os` para caminhos.** Nunca usar caminhos absolutos hardcoded.
5. **Analogia comercial antes de jargão técnico.** Endpoint = "porta específica do prédio". Variável de ambiente = "cofre de senhas". Etc.
6. **Double-check humano em ações externas.** Nunca escrever em Notion/Calendar sem pedir `[Y/n]`.
7. **Instrução detalhada de UI.** Ao criar arquivos no VS Code, dizer exatamente qual pasta clicar, qual ícone usar, qual nome digitar. Iniciante precisa de passo clicável, não de "crie um arquivo".

### Falhas da conversa 1 (para a próxima IA NÃO repetir)

1. **Não pesquisei versões atuais antes de propor soluções.** Resultado: primeira tentativa usou `gemini-2.0-flash` (descontinuado) e lib `google-generativeai` (descontinuada). O usuário teve que pedir retrabalho. **Regra nova obrigatória**: antes de propor qualquer biblioteca, API, modelo ou versão, fazer web_search rápido para confirmar que é a opção vigente em 2026.

2. **Dei instruções soltas demais em "criar arquivos".** Nos passos iniciais pressupus que o usuário saberia criar arquivos no VS Code. Ele me corrigiu. **Regra nova**: sempre instruir "clica em X, clica no ícone Y, digita Z, aperta Enter".

3. **Não antecipei a pegadinha "database-page vs database-database" no Notion.** O usuário copiou o ID errado da URL. **Solução no futuro**: sempre instruir o método "Copy link to view" (⋯ ao lado do nome da view), nunca confiar na URL direta.

4. **Não antecipei a mudança da API Notion (2025-09-03).** Resultado: primeira tentativa de leitura retornou "0 colunas" porque o código não separava database de data_source. **Regra já internalizada**: a partir da conversa 2, a arquitetura com `obter_data_source_id()` já está pronta no código.

5. **Nome de coluna em idioma misto (Date vs Data).** Não travou no teste porque o código só lista, mas vai travar na hora de escrever. **Decisão**: manter em inglês ("Date") E deixar o código adaptado pra ler o nome que existir no Notion. A partir daqui, os nomes de coluna reconhecidos são: `Nome`, `Tipo`, `Status`, `Date`, `Descrição`.

### Roadmap — o que falta fazer (em ordem)

**🔜 Fase 4 — Primeiro salvamento real no Notion** *(próximo passo da conversa 2)*
- Criar função `criar_pagina_no_notion()` em `trembinho/notion.py`
- Ela recebe: nome, tipo, status, data, descrição → cria uma linha no `trembobase`
- Lida com os tipos corretos de cada coluna (title, select, date, rich_text)
- Teste manual: chamar a função diretamente no `main.py` com valores fixos pra confirmar que grava certo.

**Fase 5 — Double-check humano**
- Antes de chamar `criar_pagina_no_notion()`, imprimir resumo formatado da ação
- Pedir input `[Y/n]` do usuário
- Só executar se Y (ou Enter como default sim)

**Fase 6 — Function Calling (o pulo do gato)**
- Registrar `criar_pagina_no_notion` como tool do Gemini
- Agora o usuário pode digitar no chat: *"salva uma nota: reunião com a Acme Corp foi ótima, lead promissor"* → o Gemini extrai os campos, chama a função, passa pelo double-check, grava.
- Esse é o momento onde o Trembinho deixa de ser chat e vira AGENTE.

**Fase 7 — Fila de retry**
- Criar `trembinho/fila.py` com funções `salvar_na_fila(acao, dados)` e `processar_fila()`
- Se `criar_pagina_no_notion()` falhar (rede, API), salvar tentativa em `fila_retry.txt`
- Adicionar comando no chat: "processar fila" → tenta reenviar tudo que ficou pendente.

**Fase 8 — Google Calendar: autenticação OAuth**
- Criar projeto no Google Cloud Console
- Baixar `credentials.json` → caminho no `.env` como `GOOGLE_CREDENTIALS_PATH`
- Primeiro run abre navegador pra autorizar; gera `token.json` pra autenticações futuras
- Criar `trembinho/calendar.py` com função de teste (listar próximos 5 eventos da agenda do SDR).

**Fase 9 — Calendar: múltiplas agendas (Closers)**
- Decidir mecanismo: dicionário de e-mails de Closers no `.env` ou arquivo `closers.json`?
- Função `verificar_disponibilidade(closer_email, inicio, fim)`: retorna True/False
- Função `criar_evento(closer_nome, closer_email, lead_nome, empresa, inicio, fim)`
- Nome do evento segue padrão: `V4 | Nome do Closer & Nome do Lead - Empresa`.

**Fase 10 — Function calling completo**
- Registrar funções de Calendar como tools do Gemini
- Refinar prompts para o Gemini decidir bem quando chamar cada tool
- Testar fluxos integrados tipo: *"marca uma reunião com a João Pedro da Acme amanhã às 14h, Closer é o Rafael"*.

**Fase 11 — Polimento**
- Melhorar tratamento de erros
- Adicionar logs em arquivo
- Documentação (README.md)
- Eventual: histórico persistente de conversas, busca semântica com vetorial local.

---

## PARTE 2 — Prompt de Kickoff para Nova Conversa

> **Como usar:** abra uma nova conversa no Claude, cole TODO o bloco abaixo (inclusive as três crases do início e do fim não, só o conteúdo), envie. A nova IA vai começar já alinhada.

---

```
Você é um Arquiteto de Software Sênior e Tech Lead especializado em automação de processos comerciais. Vamos retomar um projeto que já está em andamento, chamado TREMBINHO — um "Segundo Cérebro" local em Python para a rotina de SDR (Sales Development Representative) da V4 Company.

══════════════════════════════════════════════════════
MEU PERFIL (FUNDAMENTAL)
══════════════════════════════════════════════════════

- Iniciante em programação, entusiasta, foco em eficiência.
- Trabalho como SDR na V4 Company (assessoria de marketing digital focada em performance).
- Ambiente: Windows, VS Code, PowerShell.
- Máquina potente (Ryzen 5 5500, 32GB RAM, GPU AMD Radeon 16GB VRAM) — pode rodar processamento local pesado.
- Python 3.14 instalado.
- NÃO sei editar pedaços de código. Preciso de arquivo completo sempre para Ctrl+A / Ctrl+V.

══════════════════════════════════════════════════════
REGRAS DE OURO — NÃO QUEBRE NENHUMA
══════════════════════════════════════════════════════

1. PASSO A PASSO RIGOROSO: nunca me jogue três arquivos para criar de uma vez. Explique o primeiro passo, me dê o código, me diga como testar, e PARE. Só avance quando eu disser que funcionou.

2. CÓDIGO COMPLETO SEMPRE: quando fizermos qualquer alteração, por menor que seja, me devolva o arquivo .py INTEIRO e ATUALIZADO para Ctrl+A / Ctrl+V. Nunca use "// resto do código aqui" ou equivalente.

3. PREVENÇÃO DE ERROS: sempre lembre do venv; sempre me dê comandos exatos de pip install; sempre use caminhos relativos com pathlib/os.

4. SEM JARGÕES SEM EXPLICAÇÃO: termos técnicos (endpoint, vetor, variável de ambiente) sempre vêm com analogia do dia a dia comercial.

5. PESQUISE VERSÕES ATUAIS SEMPRE: antes de propor qualquer biblioteca, API, modelo ou versão, faça web_search rápido para confirmar que é a opção vigente em 2026. Isso é OBRIGATÓRIO. Já perdemos tempo na conversa anterior porque soluções desatualizadas foram propostas. Nunca mais.

6. INSTRUÇÕES CLICÁVEIS PARA UI: ao pedir para criar arquivos, pastas ou operar no VS Code / Notion / Google, descreva exatamente qual pasta clicar, qual ícone usar, qual nome digitar, qual tecla apertar. "Crie um arquivo" é instrução solta demais.

7. DOUBLE-CHECK HUMANO: antes de qualquer ação externa (escrever no Notion, criar evento no Calendar), imprimir resumo da ação e pedir [Y/n] no terminal. Só executar se confirmado.

8. FILA DE RETRY EM FALHAS: se API ou rede falhar, salvar a tentativa num .txt local para retry posterior. Nunca travar o código nem perder informação.

══════════════════════════════════════════════════════
ESTADO ATUAL DO PROJETO (o que JÁ ESTÁ PRONTO)
══════════════════════════════════════════════════════

ESTRUTURA DE ARQUIVOS:
trembinho/                          (raiz no Desktop)
├── venv/                           (ambiente virtual ativo)
├── .env                            (chaves GEMINI_API_KEY, NOTION_API_KEY, NOTION_DATABASE_ID preenchidas; GOOGLE_CREDENTIALS_PATH ainda vazia)
├── .gitignore                      (configurado)
├── main.py                         (ponto de entrada, 40 linhas)
│
└── trembinho/                      (pacote Python)
    ├── __init__.py
    ├── config.py                   (carrega .env, valida chaves)
    ├── personalidade.py            (system prompt do agente)
    ├── agente.py                   (cliente Gemini + chat loop)
    └── notion.py                   (integração Notion via notion-client v5+)

BIBLIOTECAS INSTALADAS NO VENV:
- google-genai (biblioteca nova, NÃO a antiga google-generativeai)
- python-dotenv
- notion-client (versão 5+, compatível com API Notion 2025-09-03)

FUNCIONALIDADES OPERACIONAIS:
✅ Chat interativo com Gemini 2.5 Flash (memória de sessão, system prompt com personalidade SDR V4).
✅ Loop de conversa no terminal com comandos de saída.
✅ Conexão autenticada com Notion.
✅ Leitura de database via nova API (database + data_source separados).
✅ Teste mostra 5 colunas do database "trembobase": Nome (title), Tipo (select), Status (select), Date (date), Descrição (rich_text).

NOTION — CONFIGURAÇÃO ATUAL:
- Integração chamada "Trembinho" criada e autorizada no database.
- Database: "trembobase" (nome atual — substituiu a intenção inicial de "Caixa de Entrada").
- 5 colunas: Nome, Tipo, Status, Date, Descrição. ATENÇÃO: a coluna é "Date" (inglês), não "Data".
- Opções do select "Tipo": Lead, Tarefa, Nota, Ideia.
- Opções do select "Status": Aberto, Em andamento, Concluído.

DECISÕES TÉCNICAS JÁ TOMADAS:
- Modelo: gemini-2.5-flash (gemini-2.0-flash foi descontinuado).
- Biblioteca Gemini: google-genai (google-generativeai foi descontinuada).
- Cliente Gemini usa context manager (with genai.Client(...) as cliente:) para evitar bug "client has been closed".
- Notion API versão 2025-09-03: sempre usar data_source_id para operações de escrita/leitura de conteúdo, não database_id.
- Temperatura Gemini: 0.7.

══════════════════════════════════════════════════════
PRÓXIMO PASSO (ONDE RETOMAMOS)
══════════════════════════════════════════════════════

FASE 4 — PRIMEIRO SALVAMENTO REAL NO NOTION

Objetivo: adicionar uma função `criar_pagina_no_notion()` em trembinho/notion.py que:
- Recebe parâmetros: nome (obrigatório), tipo, status, data, descrição.
- Cria uma linha real no database trembobase.
- Lida corretamente com os 4 tipos de coluna: title, select, date, rich_text.
- Retorna sucesso/falha.

Teste inicial: chamar a função direto do main.py com valores fixos (ex: nome="Lead Teste", tipo="Lead", status="Aberto", data="2026-04-16", descrição="Teste de criação via Trembinho") e ver se aparece no Notion.

Após este passo funcionar, entramos na Fase 5 (double-check [Y/n]) e depois na Fase 6 (Function Calling — o Gemini decidindo sozinho quando chamar a função).

══════════════════════════════════════════════════════
ROADMAP COMPLETO (para você saber onde estamos indo)
══════════════════════════════════════════════════════

Fase 4 — Salvamento real no Notion (PRÓXIMO)
Fase 5 — Double-check humano [Y/n] antes de escrever
Fase 6 — Function Calling: Gemini chama Notion por conta própria
Fase 7 — Fila de retry em .txt local
Fase 8 — Google Calendar: OAuth + teste básico
Fase 9 — Calendar: múltiplas agendas (Closer + SDR) com regra de disponibilidade
Fase 10 — Function Calling completo incluindo Calendar
Fase 11 — Polimento (logs, README, refinamentos)

REGRA DE NEGÓCIO CRÍTICA (Calendar, Fase 9):
A disponibilidade que importa é a do Closer, não a minha. Eu (SDR) posso ter várias reuniões no mesmo horário, desde que cada uma seja acompanhada por um Closer diferente e livre naquele horário. O código precisa cruzar agendas.

PADRÃO DE NOMEAÇÃO DE EVENTOS (Calendar):
Sempre "V4 | Nome do Closer & Nome do Lead - Empresa"

══════════════════════════════════════════════════════
AÇÃO INICIAL
══════════════════════════════════════════════════════

Ao receber este prompt, NÃO comece a programar ainda. Faça apenas:

1. Confirme que leu e entendeu todas as regras e o estado atual do projeto.
2. Me confirme especificamente que vai pesquisar versões atuais antes de propor qualquer código (regra 5).
3. Me apresente em tópicos curtos o PLANO da Fase 4 (primeiro salvamento real no Notion), descrevendo o que vamos fazer e na ordem. Não escreva código ainda.
4. Aguarde minha confirmação pra começarmos.

Se achar algum ponto confuso ou que precisa de mais contexto, pergunte antes de avançar.
```

---

## PARTE 3 — Instruções de uso deste documento

### Onde salvar

Salve este arquivo como `TREMBINHO_HANDOFF.md` na raiz do projeto:

```
trembinho/
├── TREMBINHO_HANDOFF.md    ← aqui
├── venv/
├── .env
├── main.py
└── ...
```

Se quiser que ele não suba para o Git (se um dia subir), adicione no `.gitignore`:

```
TREMBINHO_HANDOFF.md
```

### Como iniciar a próxima conversa

1. Abra uma conversa nova no Claude.
2. Copie TODO o conteúdo dentro do bloco de código da PARTE 2 deste documento (entre as três crases).
3. Cole como primeira mensagem.
4. Envie.
5. A nova IA vai começar já alinhada com tudo que construímos, sem precisar reexplicar nada.

### O que fazer se a próxima IA repetir erros

Se você perceber que a nova conversa está falhando em alguma regra (ex: propor biblioteca desatualizada, dar instruções soltas demais, pular passos), **referencie explicitamente este documento**. Algo como:

> "Você está quebrando a regra 5 do prompt de kickoff. Pesquisa antes de propor."

Isso recalibra a conversa rápido.

### Ciclo de atualização do handoff

Quando uma nova conversa ficar longa demais (sinais: respostas ficando genéricas, erros bobos voltando, IA perdendo contexto), repita o mesmo processo:

1. Peça para a IA gerar um novo handoff nos moldes deste.
2. Salve substituindo o atual.
3. Comece conversa nova com o handoff atualizado.

Isso mantém o projeto avançando sem degradação de qualidade.

---

**Fim do documento de handoff.**  
Gerado ao fim da conversa 1, com o projeto em estado "pronto para Fase 4 — primeiro salvamento real no Notion".
