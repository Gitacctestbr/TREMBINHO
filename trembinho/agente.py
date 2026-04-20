"""
TREMBINHO - Motor do Agente (Ollama + Qwen 2.5 14B)
====================================================
Foco: assertividade, interpretação de linguagem natural e Blindagem Nível 2
(higienização de campos e interceptação de JSON vazado pelo modelo local).

SPRINT 4 - REFATORAÇÃO PARA BIDIRECIONAL:
- processar_mensagem() extraída como função pura (texto_in -> texto_out).
- rodar_agente() vira casca fina de terminal.
- Blindagem Nível 2 preservada 100%.
- Instrução mestre centralizada para reuso pelo Telegram Listener.

SPRINT 4 / PASSO 5:
- processar_mensagem() aceita auto_confirmar_gravacao para pular [Y/n]
  quando a chamada vem do Telegram (canal assíncrono).

SPRINT 4 / PASSO 5.5 - HOTFIX DE EXTRAÇÃO:
- Blindagem Nível 3: extração heurística de `nome` quando o Qwen falha.
- Propagação forçada do hint [DATA_INTERPRETADA_PELO_SISTEMA] quando data vem vazia.
- DEBUG_EXTRACAO: log visível do args cru pra troubleshooting.

SPRINT 4 / PASSO 5.6 - FORMATAÇÃO RICA + DESCRIÇÃO LIVRE:
- _formatar_listagem(): consome list[dict] do novo contrato do notion.py e
  devolve string HTML estilo "bullet denso" para o Telegram.
- _formatar_confirmacao_salvamento(): resposta consistente pós-gravação.
- _extrair_descricao_heuristica(): fallback quando o Qwen deixa descricao vazia.

SPRINT 4 / PASSO 5.6.C - FORMATAÇÃO COMPACTA PARA PUSH DIÁRIO:
- _formatar_listagem_compacta(): versão sem cabeçalho/rodapé, pra ser
  embutida no copy narrativo do verificar_pendencias.py (BOM DIA CHEFE etc).

SPRINT 7 / PASSO 1 - MÚLTIPLOS TOOL CALLS:
- Suporte a MÚLTIPLOS tool_calls por mensagem (loop em vez de [0]).
  Fix para mensagens compostas tipo "agenda lembrete + salva no notion".
- _executar_tool_call(): rotas extraídas em função auxiliar pra permitir
  execução em loop sem duplicar código.

SPRINT 8 - BLINDAGEM N4 ESTRUTURAL:
- Removida a lista GATILHOS_ALUCINACAO (14 regex frágeis).
- Removida _detectar_alucinacao_execucao().
- Blindagem N4 substituída por validação puramente estrutural: se msg.tool_calls
  é None e o content não é JSON residual, é resposta conversacional legítima.
- A prevenção de alucinação agora ocorre no nível do prompt (personalidade v9),
  não por regex post-hoc.
"""

import ollama
import json
import re
from datetime import datetime
from trembinho.personalidade import PERSONALIDADE_TREMBINHO
from trembinho.notion import criar_pagina_no_notion, listar_itens_no_notion, buscar_paginas_por_nome, atualizar_pagina_no_notion, excluir_pagina_no_notion, excluir_itens_por_filtro
from trembinho.datas import interpretar_data
from trembinho.agendador import (
    agendar_notificacao,
    interpretar_tempo_relativo,
    formatar_disparo_humano,
    listar_pendentes,
    cancelar_notificacao,
    editar_notificacao,
    buscar_notificacao_por_contexto,
    formatar_lista_notificacoes,
)

# -----------------------------------------------------------------------------
# Configuração do motor local
# -----------------------------------------------------------------------------
MODELO_LOCAL = "qwen2.5:14b"
COMANDOS_DE_SAIDA = ["sair", "exit", "quit", "fechar"]

# Flag temporária pra debug do hotfix. Depois de validado, mudar pra False.
DEBUG_EXTRACAO = False

# temperature=0.3 -> deixa o Qwen obediente ao function calling, menos criativo.
OPCOES_OLLAMA = {
    "temperature": 0.3,
    "num_ctx": 8192,
}

# Nomes considerados "vazios" ou "genéricos" que devem acionar fallback heurístico
NOMES_GENERICOS_SUSPEITOS = {
    "", "nova entrada", "lead novo", "tarefa nova", "nota nova",
    "sem nome", "n/a", "nova tarefa", "novo lead", "entrada", "item",
    "none", "null",
}

# Descrições consideradas genéricas/vazias que devem acionar heurística
DESCRICOES_GENERICAS = {
    "", "none", "null", "n/a", "-", "vazio",
}

# Nomes canônicos das ferramentas — usado pra validar tool_calls detectados
FUNCOES_VALIDAS = {
    "ferramenta_salvar_notion",
    "ferramenta_listar_notion",
    "ferramenta_editar_notion",
    "ferramenta_excluir_notion",
    "ferramenta_agendar_notificacao",
    "ferramenta_listar_notificacoes",
    "ferramenta_cancelar_notificacao",
    "ferramenta_editar_notificacao",
}


# -----------------------------------------------------------------------------
# Ferramentas expostas ao Qwen via function calling
# -----------------------------------------------------------------------------
def ferramenta_salvar_notion(nome: str, tipo: str, status: str, data: str, descricao: str) -> bool:
    """
    Salva uma entrada no Notion. Use para REGISTRAR, ADICIONAR ou SALVAR.
    """
    pass

def ferramenta_listar_notion(tipo: str = None, status: str = None, data_inicio: str = None, data_fim: str = None) -> bool:
    """
    Busca e lista itens do Notion com base em filtros de período. Use para CONSULTAR, LISTAR ou VER.
    Args:
        tipo: Opcional. Um de [Lead, Tarefa, Nota, Ideia].
        status: Opcional. Um de [Aberto, Em andamento, Concluído].
        data_inicio: Opcional. Formato YYYY-MM-DD. Data inicial da busca.
        data_fim: Opcional. Formato YYYY-MM-DD. Data final da busca.
    """
    pass

def ferramenta_excluir_notion(nome_busca: str = "", tipo: str = "", status: str = "") -> bool:
    """
    Remove (arquiva) uma ou mais entradas existentes no Notion.
    Use para DELETAR, EXCLUIR, APAGAR ou REMOVER.

    MODOS DE USO (escolha UM):
    1. Exclusão pontual: passe `nome_busca` (parte do nome do item).
    2. Exclusão em massa por tipo: passe `tipo` em ["Lead","Tarefa","Nota","Ideia"].
       Ex: "apague todas as ideias" → tipo="Ideia".
    3. Exclusão em massa por status: passe `status` em ["Aberto","Em andamento","Concluído"].
       Ex: "remove tudo que já está concluído" → status="Concluído".
    4. Filtro combinado: tipo + status juntos também é permitido.

    REGRA: Preencha APENAS os campos que se aplicam. Use string vazia "" nos demais.
    NUNCA invente nomes genéricos. Se o pedido for em massa, deixe nome_busca="" e use tipo/status.

    Args:
        nome_busca: Parte do nome do item específico. "" quando for em massa.
        tipo: "Lead" | "Tarefa" | "Nota" | "Ideia". "" quando não filtrar por tipo.
        status: "Aberto" | "Em andamento" | "Concluído". "" quando não filtrar por status.
    """
    pass

def ferramenta_agendar_notificacao(tempo: str, contexto: str) -> bool:
    """
    Agenda uma notificação para enviar ao SDR via Telegram após o tempo especificado.
    Use para NOTIFICAR, LEMBRAR, AVISAR ou ALERTAR o SDR em um horário futuro.
    Args:
        tempo: Expressão de tempo quando disparar. Ex: "em 5 minutos", "daqui 2 horas", "às 14h30".
        contexto: O que o SDR precisa ser lembrado. Ex: "enviar relatório para Rhuan".
    """
    pass

def ferramenta_listar_notificacoes() -> bool:
    """
    Lista todas as notificações agendadas e pendentes.
    Use quando o SDR perguntar quais lembretes tem agendados, quais notificações estão ativas, etc.
    """
    pass

def ferramenta_cancelar_notificacao(id_ou_contexto: str) -> bool:
    """
    Cancela uma notificação pendente. Use para CANCELAR, REMOVER, DELETAR ou DESATIVAR um lembrete.
    Args:
        id_ou_contexto: ID de 8 chars (ex: "a3f2b1c4") OU parte do texto do lembrete a cancelar.
    """
    pass

def ferramenta_editar_notificacao(id_ou_contexto: str, novo_tempo: str = "", novo_contexto: str = "") -> bool:
    """
    Edita o horário ou o texto de uma notificação pendente. Use para EDITAR, MUDAR, ALTERAR ou ADIAR um lembrete.
    Args:
        id_ou_contexto: ID de 8 chars OU parte do texto do lembrete a editar.
        novo_tempo: Nova expressão de tempo. Ex: "às 15h30", "amanhã às 9h". Deixe "" se não mudar.
        novo_contexto: Novo texto do lembrete. Deixe "" se não mudar.
    """
    pass

def ferramenta_editar_notion(nome_busca: str, novo_nome: str = "", novo_tipo: str = "", novo_status: str = "", nova_data: str = "", nova_descricao: str = "") -> bool:
    """
    Edita uma entrada existente no Notion. Use para EDITAR, MUDAR, ALTERAR, ATUALIZAR ou CORRIGIR.
    Args:
        nome_busca: Nome (ou parte do nome) da entrada a localizar. OBRIGATÓRIO.
        novo_nome: Novo nome. Deixe "" se não mudar.
        novo_tipo: Um de [Lead, Tarefa, Nota, Ideia]. Deixe "" se não mudar.
        novo_status: Um de [Aberto, Em andamento, Concluído]. Deixe "" se não mudar.
        nova_data: Data no formato YYYY-MM-DD ou YYYY-MM-DDTHH:MM:00. Deixe "" se não mudar.
        nova_descricao: Nova descrição. Deixe "" se não mudar.
    """
    pass

# -----------------------------------------------------------------------------
# Pré-processamento e Blindagem
# -----------------------------------------------------------------------------
def _enriquecer_mensagem_com_data(mensagem_original):
    data_interpretada = interpretar_data(mensagem_original)
    if not data_interpretada:
        return mensagem_original
    return mensagem_original + f"\n[DATA_INTERPRETADA_PELO_SISTEMA: {data_interpretada}]"

def formatar_data_iso(data_str, mensagem_original=""):
    hoje = datetime.now()
    data_str = str(data_str or "").strip()

    for formato in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(data_str, formato).strftime(
                "%Y-%m-%dT%H:%M:00" if "T" in data_str else "%Y-%m-%d"
            )
        except (ValueError, TypeError):
            continue

    try:
        return datetime.strptime(data_str, "%d/%m/%Y").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        pass

    if data_str:
        interpretado = interpretar_data(data_str)
        if interpretado:
            return interpretado

    if mensagem_original:
        interpretado = interpretar_data(mensagem_original)
        if interpretado:
            return interpretado

    return hoje.strftime("%Y-%m-%d")

# -----------------------------------------------------------------------------
# BLINDAGEM NÍVEL 3 - Extração heurística de nome
# -----------------------------------------------------------------------------
_PALAVRAS_BULK = {
    "todas", "todos", "tudo", "todinhos", "todinhas", "cada",
    "qualquer", "quaisquer", "all",
}

def _mensagem_tem_intencao_bulk(mensagem_original):
    """
    Detecta se a mensagem do SDR sinaliza operação EM MASSA
    (ex: "apague todas as ideias", "remove tudo que está concluído").
    """
    if not mensagem_original:
        return False
    txt = mensagem_original.lower()
    return any(re.search(rf"\b{re.escape(p)}\b", txt) for p in _PALAVRAS_BULK)


def _extrair_nome_heuristico(mensagem_original, tipo_inferido):
    """
    Fallback de emergência quando o Qwen não preenche o campo 'nome'.
    Usa regex pra capturar o nome provável baseado em padrões brasileiros.

    Args:
        mensagem_original: texto cru que o SDR mandou.
        tipo_inferido: "Lead" ou "Tarefa" (muda a estratégia de extração).

    Returns:
        String com o nome extraído ou None se não conseguir.
    """
    if not mensagem_original:
        return None

    # GUARDA BULK: se é intenção em massa, nunca extrair nome pontual.
    # Evita capturar palavras capitalizadas de verbos imperativos (ex: "Que Você Exclua").
    if _mensagem_tem_intencao_bulk(mensagem_original):
        return None

    texto = mensagem_original.strip()

    # -------------------------------------------------------------------------
    # ESTRATÉGIA 1 - LEAD: pessoa (nome próprio capitalizado)
    # -------------------------------------------------------------------------
    if tipo_inferido == "Lead":
        # Padrões: "pra Luiza", "para João da XP", "lead Matheus", "o Carlos da Rappi"
        padroes_lead = [
            r"(?:pra|para)\s+([A-ZÁÉÍÓÚÃÕÂÊÎÔÛÇ][\wáéíóúãõâêîôûç]+(?:\s+[A-ZÁÉÍÓÚÃÕÂÊÎÔÛÇ]?[\wáéíóúãõâêîôûç]+){0,3})",
            r"(?:lead|contato|prospect|cliente)\s+([A-ZÁÉÍÓÚÃÕÂÊÎÔÛÇ][\wáéíóúãõâêîôûç]+(?:\s+[A-ZÁÉÍÓÚÃÕÂÊÎÔÛÇ]?[\wáéíóúãõâêîôûç]+){0,3})",
            r"(?:o|a|do|da)\s+([A-ZÁÉÍÓÚÃÕÂÊÎÔÛÇ][\wáéíóúãõâêîôûç]+(?:\s+[A-ZÁÉÍÓÚÃÕÂÊÎÔÛÇ]?[\wáéíóúãõâêîôûç]+){0,2})",
        ]
        for padrao in padroes_lead:
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                candidato = match.group(1).strip()
                # Capitaliza cada palavra corretamente
                return " ".join(w.capitalize() for w in candidato.split())

        # Fallback: primeira palavra capitalizada que não é verbo comum
        match_cap = re.search(r"\b([A-ZÁÉÍÓÚÃÕÂÊÎÔÛÇ][a-záéíóúãõâêîôûç]{2,})\b", texto)
        if match_cap:
            return match_cap.group(1)

    # -------------------------------------------------------------------------
    # ESTRATÉGIA 2 - TAREFA: ação em infinitivo
    # -------------------------------------------------------------------------
    if tipo_inferido == "Tarefa":
        # Verbos comuns de ação SDR: ligar, falar, mandar, enviar, agendar, fazer
        padrao_acao = re.search(
            r"(?:é\s+)?(ligar|falar|mandar|enviar|agendar|fazer|marcar|buscar|responder|preparar|estudar|revisar|organizar|atualizar|montar|criar)\s+"
            r"(?:com\s+|para\s+|pro\s+|pra\s+|o\s+|a\s+)?"
            r"([\wáéíóúãõâêîôûç][\wáéíóúãõâêîôûç\s]{2,40}?)"
            r"(?=\s*(?:amanhã|hoje|ontem|$|\.|,|às|as|em\s+\d))",
            texto, re.IGNORECASE
        )
        if padrao_acao:
            verbo = padrao_acao.group(1).lower()
            objeto = padrao_acao.group(2).strip()
            return f"{verbo.capitalize()} com {objeto}" if verbo in ("falar", "conversar") else f"{verbo.capitalize()} {objeto}"

    return None


def _extrair_data_forcada_da_mensagem(mensagem_original):
    """
    Último recurso: extrai data do marcador [DATA_INTERPRETADA_PELO_SISTEMA]
    injetado na mensagem ou do próprio texto cru.
    """
    if not mensagem_original:
        return None

    # Prioridade 1: o hint que a gente mesmo injetou
    match_hint = re.search(r"\[DATA_INTERPRETADA_PELO_SISTEMA:\s*([^\]]+)\]", mensagem_original)
    if match_hint:
        return match_hint.group(1).strip()

    # Prioridade 2: interpretar direto do texto
    return interpretar_data(mensagem_original)


# -----------------------------------------------------------------------------
# BLINDAGEM NÍVEL 3 - Extração heurística de DESCRIÇÃO (Passo 5.6)
# -----------------------------------------------------------------------------
def _extrair_descricao_heuristica(mensagem_original, nome_extraido, tipo_inferido):
    """
    Fallback de descrição quando o Qwen deixa o campo vazio.

    Estratégia: remove do texto cru os verbos de comando, o nome já capturado
    e os marcadores de data/hora. O que sobrar é "contexto útil" que o SDR
    mencionou — vira a descrição.

    Se sobrar muito pouco ou nada, gera descrição contextual baseada no tipo.

    Args:
        mensagem_original: texto cru do SDR.
        nome_extraido: nome já definido (pra remover do texto e não duplicar).
        tipo_inferido: "Lead" | "Tarefa" | "Nota" | "Ideia".

    Returns:
        String de descrição. Nunca None, nunca vazia.
    """
    if not mensagem_original:
        return _descricao_default_por_tipo(tipo_inferido)

    texto = mensagem_original.strip()

    # -------------------------------------------------------------------------
    # LIMPEZA 1: remove o hint injetado pelo sistema
    # -------------------------------------------------------------------------
    texto = re.sub(r"\[DATA_INTERPRETADA_PELO_SISTEMA:[^\]]+\]", "", texto)

    # -------------------------------------------------------------------------
    # LIMPEZA 2: remove verbos de comando do início
    # -------------------------------------------------------------------------
    texto = re.sub(
        r"^(salva|salve|anota|anote|registra|registre|joga\s+a[íi]|adiciona|adicione|"
        r"cria|crie|marca|marque|cadastra|cadastre|bota|bote|coloca|coloque|"
        r"da\s+um\s+salve|dá\s+um\s+salve)\s+",
        "",
        texto,
        flags=re.IGNORECASE,
    )

    # -------------------------------------------------------------------------
    # LIMPEZA 3: remove marcadores de data/hora inteiros
    # -------------------------------------------------------------------------
    padroes_data_hora = [
        r"\b(hoje|amanh[ãa]|ontem|depois\s+de\s+amanh[ãa])\b",
        r"\b(pr[óo]xim[ao]\s+|essa\s+|esta\s+)?(segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo)(-feira)?(\s+que\s+vem)?\b",
        r"\b[àa]s?\s+\d{1,2}[:h]\d{0,2}\b",
        r"\b\d{1,2}[:h]\d{2}\b",
        r"\b\d{1,2}h\b",
        r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",
        r"\bdaqui\s+a?\s*\d+\s+(dia|dias|semana|semanas|m[eê]s|m[eê]ses)\b",
        r"\bem\s+\d+\s+(dia|dias|semana|semanas|m[eê]s|m[eê]ses)\b",
        r"\bpr[ao]\s+(?=amanh[ãa]|hoje|segunda|ter[çc]a|quarta|quinta|sexta)",  # "pra amanhã" -> remove o "pra"
    ]
    for padrao in padroes_data_hora:
        texto = re.sub(padrao, "", texto, flags=re.IGNORECASE)

    # -------------------------------------------------------------------------
    # LIMPEZA 4: remove o nome já extraído (evita duplicação na descrição)
    # -------------------------------------------------------------------------
    if nome_extraido:
        # Remove o nome completo
        texto = re.sub(re.escape(nome_extraido), "", texto, flags=re.IGNORECASE)
        # Remove partes do nome (primeiro+último) caso tenha aparecido fragmentado
        for parte in nome_extraido.split():
            if len(parte) > 3:  # só remove palavras significativas (não "da", "do")
                texto = re.sub(rf"\b{re.escape(parte)}\b", "", texto, flags=re.IGNORECASE)

    # -------------------------------------------------------------------------
    # LIMPEZA 5: remove partículas conectoras que sobraram soltas
    # -------------------------------------------------------------------------
    texto = re.sub(
        r"\b(lead|contato|prospect|cliente|tarefa|nota|ideia|pra|para|pro|"
        r"de|do|da|o|a|um|uma|que|é|eu|mim|com|no|na)\b",
        " ",
        texto,
        flags=re.IGNORECASE,
    )

    # Colapsa múltiplos espaços e pontuação residual
    texto = re.sub(r"[,;:\s]+", " ", texto).strip(" .,;:-")

    # -------------------------------------------------------------------------
    # DECISÃO FINAL: o resíduo é útil?
    # -------------------------------------------------------------------------
    # Precisa ter pelo menos 8 chars pra ser considerado "contexto útil"
    if len(texto) >= 8:
        # Primeira letra maiúscula, termina com ponto
        texto = texto[0].upper() + texto[1:]
        if not texto.endswith("."):
            texto += "."
        return texto

    # Resíduo muito curto ou vazio -> default por tipo
    return _descricao_default_por_tipo(tipo_inferido)


def _descricao_default_por_tipo(tipo):
    """Descrição contextual quando não dá pra extrair nada útil da mensagem."""
    defaults = {
        "Lead": "Lead prospectado via Trembinho. Primeiro contato pendente.",
        "Tarefa": "Tarefa registrada via Trembinho. Aguardando execução.",
        "Nota": "Nota rápida via Trembinho.",
        "Ideia": "Ideia capturada via Trembinho.",
    }
    return defaults.get(tipo, "Registrado via Trembinho.")


# -----------------------------------------------------------------------------
# FORMATAÇÃO DE SAÍDA - Telegram/terminal (Passo 5.6)
# -----------------------------------------------------------------------------
# Mapeamentos visuais
EMOJI_TIPO = {
    "Lead": "👤",
    "Tarefa": "📞",
    "Nota": "📝",
    "Ideia": "💡",
}

EMOJI_STATUS = {
    "Aberto": "🟢",
    "Em andamento": "🟡",
    "Concluído": "✅",
}

MESES_ABREV = {
    1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun",
    7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez",
}


def _formatar_data_humana(data_iso):
    """
    Converte '2026-04-18T10:00:00.000-03:00' → '18/abr 10:00'
            '2026-04-18'                        → '18/abr'
            'Sem data' ou None                  → 'sem data'
    """
    if not data_iso or data_iso == "Sem data":
        return "sem data"

    s = str(data_iso).strip()

    # Separa data e hora
    if "T" in s:
        parte_data, parte_hora = s.split("T", 1)
        # Remove offset e milissegundos da hora
        parte_hora = re.split(r"[+\-Z]", parte_hora)[0]
        parte_hora = parte_hora.split(".")[0]  # tira .000
        hora_str = ":".join(parte_hora.split(":")[:2]) if ":" in parte_hora else ""
    else:
        parte_data = s
        hora_str = ""

    # Parseia YYYY-MM-DD
    try:
        dt = datetime.strptime(parte_data, "%Y-%m-%d")
        data_legivel = f"{dt.day:02d}/{MESES_ABREV[dt.month]}"
    except (ValueError, KeyError):
        return s  # devolve cru se não conseguiu parsear

    if hora_str and hora_str != "00:00":
        return f"{data_legivel} {hora_str}"
    return data_legivel


def _formatar_cabecalho_filtros(tipo, status, data_inicio, data_fim):
    """
    Monta o cabeçalho da listagem com os filtros aplicados.
    Ex: '🎯 <b>Tarefas • Aberto • hoje</b>'
    """
    # Tipo (pluralizado quando filtrado)
    if tipo:
        plural = {"Lead": "Leads", "Tarefa": "Tarefas", "Nota": "Notas", "Ideia": "Ideias"}.get(tipo, tipo)
        partes = [plural]
    else:
        partes = ["Pipeline"]

    # Status
    if status:
        partes.append(status)

    # Período
    hoje_str = datetime.now().strftime("%Y-%m-%d")
    if data_inicio and data_fim:
        d_ini = data_inicio.split("T")[0]
        d_fim = data_fim.split("T")[0]
        if d_ini == d_fim:
            if d_ini == hoje_str:
                partes.append("hoje")
            else:
                partes.append(_formatar_data_humana(d_ini))
        else:
            partes.append(f"{_formatar_data_humana(d_ini)} → {_formatar_data_humana(d_fim)}")
    elif data_inicio:
        partes.append(f"desde {_formatar_data_humana(data_inicio)}")
    elif data_fim:
        partes.append(f"até {_formatar_data_humana(data_fim)}")

    return f"🎯 <b>{' • '.join(partes)}</b>"


def _formatar_listagem(itens, tipo=None, status=None, data_inicio=None, data_fim=None):
    """
    Converte list[dict] do notion.py em string HTML estilo bullet denso:

    🎯 <b>Tarefas • Aberto • hoje</b>

    • 📞 Ligar para Rafael — 📅 18/abr 10:00 🟢
    • 📞 Mandar proposta Gustavo — 📅 18/abr 🟢

    Args:
        itens: list[dict] com chaves nome/tipo/status/data/descricao,
               OU dict {"erro": "..."}.
        tipo/status/data_inicio/data_fim: filtros aplicados (pro cabeçalho).

    Returns:
        String HTML pronta pra enviar ao Telegram.
    """
    # Caso de erro
    if isinstance(itens, dict) and "erro" in itens:
        return f"❌ {itens['erro']}"

    cabecalho = _formatar_cabecalho_filtros(tipo, status, data_inicio, data_fim)

    # Lista vazia
    if not itens:
        return f"{cabecalho}\n\n<i>Nada por aqui. Campo limpo. 🧹</i>"

    # Monta as linhas
    linhas = []
    for item in itens:
        nome = item.get("nome", "Sem título")
        tipo_item = item.get("tipo", "?")
        status_item = item.get("status", "?")
        data_item = item.get("data", "")

        emoji_t = EMOJI_TIPO.get(tipo_item, "•")
        emoji_s = EMOJI_STATUS.get(status_item, "")
        data_humana = _formatar_data_humana(data_item)

        linhas.append(f"• {emoji_t} {nome} — 📅 {data_humana} {emoji_s}".rstrip())

    total = len(itens)
    rodape = f"\n\n<i>{total} {'item' if total == 1 else 'itens'}</i>"

    return f"{cabecalho}\n\n" + "\n".join(linhas) + rodape


def _formatar_listagem_compacta(itens, vazio_fallback="<i>Tudo limpo por aqui!</i>"):
    """
    Versão SEM cabeçalho e SEM rodapé da listagem. Usada pelo verificar_pendencias.py
    pra embutir os bullets dentro do copy narrativo (BOM DIA CHEFE etc).

    Args:
        itens: list[dict] do notion.py OU dict {"erro": "..."}.
        vazio_fallback: string HTML a retornar quando não há itens.

    Returns:
        Só as linhas de bullet (ou o fallback de vazio/erro).
    """
    # Caso de erro
    if isinstance(itens, dict) and "erro" in itens:
        return f"<i>❌ {itens['erro']}</i>"

    # Lista vazia
    if not itens:
        return vazio_fallback

    linhas = []
    for item in itens:
        nome = item.get("nome", "Sem título")
        tipo_item = item.get("tipo", "?")
        status_item = item.get("status", "?")
        data_item = item.get("data", "")

        emoji_t = EMOJI_TIPO.get(tipo_item, "•")
        emoji_s = EMOJI_STATUS.get(status_item, "")
        data_humana = _formatar_data_humana(data_item)

        linhas.append(f"• {emoji_t} {nome} — 📅 {data_humana} {emoji_s}".rstrip())

    return "\n".join(linhas)


def _formatar_confirmacao_salvamento(nome, tipo, status, data_iso):
    """
    Resposta de confirmação após gravação bem-sucedida.
    Ex: '✅ <b>Tarefa</b> salva: Ligar para Rafael\n📅 18/abr 10:00 🟢 Aberto'
    """
    emoji_s = EMOJI_STATUS.get(status, "")
    data_humana = _formatar_data_humana(data_iso)
    return (
        f"✅ <b>{tipo}</b> salva no pipeline:\n"
        f"<b>{nome}</b>\n"
        f"📅 {data_humana} {emoji_s} {status}"
    )


def _formatar_confirmacao_edicao(item, campos_alterados):
    """Confirmação após edição bem-sucedida de um item existente."""
    nome = item.get("nome", "?")
    tipo = item.get("tipo", "?")
    status_final = campos_alterados.get("status") or item.get("status", "?")
    data_final = campos_alterados.get("data") or item.get("data", "")
    emoji_s = EMOJI_STATUS.get(status_final, "")
    data_humana = _formatar_data_humana(data_final)
    campos_txt = ", ".join(campos_alterados.keys())
    return (
        f"✏️ <b>{tipo}</b> atualizado:\n"
        f"<b>{nome}</b>\n"
        f"📅 {data_humana} {emoji_s} {status_final}\n"
        f"<i>Campos alterados: {campos_txt}</i>"
    )


def _formatar_confirmacao_exclusao(item):
    """Confirmação após arquivamento bem-sucedido."""
    nome = item.get("nome", "?")
    tipo = item.get("tipo", "?")
    emoji_t = EMOJI_TIPO.get(tipo, "•")
    return (
        f"🗑️ {emoji_t} <b>{nome}</b> removido do pipeline.\n"
        f"<i>(Arquivado no Notion — dá pra restaurar pelo site se precisar.)</i>"
    )


def _formatar_confirmacao_exclusao_massa(arquivados, falhas, tipo=None, status=None):
    """
    Confirmação após exclusão em massa por filtro.

    Args:
        arquivados: list[dict] com itens removidos.
        falhas: list[dict] com itens que falharam.
        tipo / status: filtros aplicados (pra compor o cabeçalho).

    Returns:
        String HTML com resumo + bullets dos itens apagados.
    """
    total_ok = len(arquivados)
    total_falhou = len(falhas)

    # Cabeçalho descritivo do filtro
    partes_filtro = []
    if tipo:
        plural = {"Lead": "Leads", "Tarefa": "Tarefas", "Nota": "Notas", "Ideia": "Ideias"}.get(tipo, tipo)
        partes_filtro.append(plural)
    if status:
        partes_filtro.append(status)
    filtro_txt = " • ".join(partes_filtro) if partes_filtro else "itens"

    if total_ok == 0 and total_falhou == 0:
        return f"<i>Nenhum item encontrado com filtro <b>{filtro_txt}</b>. Nada a remover.</i>"

    linhas = [f"🗑️ <b>Exclusão em massa — {filtro_txt}</b>"]
    linhas.append("")

    if arquivados:
        for item in arquivados:
            nome = item.get("nome", "?")
            tipo_item = item.get("tipo", "?")
            emoji_t = EMOJI_TIPO.get(tipo_item, "•")
            linhas.append(f"• {emoji_t} {nome}")

    linhas.append("")
    resumo = f"<i>{total_ok} item{'s' if total_ok != 1 else ''} arquivado{'s' if total_ok != 1 else ''}"
    if total_falhou:
        resumo += f" — ⚠️ {total_falhou} falha(s)"
    resumo += ". Dá pra restaurar pelo site do Notion.</i>"
    linhas.append(resumo)

    return "\n".join(linhas)


def _formatar_opcoes_para_escolha(resultados):
    """Lista itens encontrados para o usuário escolher qual editar."""
    linhas = []
    for i, item in enumerate(resultados, 1):
        nome = item.get("nome", "?")
        tipo = item.get("tipo", "?")
        status = item.get("status", "?")
        data = _formatar_data_humana(item.get("data", ""))
        emoji_t = EMOJI_TIPO.get(tipo, "•")
        emoji_s = EMOJI_STATUS.get(status, "")
        linhas.append(f"{i}. {emoji_t} <b>{nome}</b> — {tipo} — {data} {emoji_s}")
    return "\n".join(linhas)


# -----------------------------------------------------------------------------
# Instrução mestre (system prompt) - centralizada para reuso
# -----------------------------------------------------------------------------
def _montar_instrucao_mestre():
    """Monta o system prompt com contexto temporal atualizado."""
    data_hoje = datetime.now().strftime("%Y-%m-%d")
    return f"""{PERSONALIDADE_TREMBINHO}

=============================================================
CONTEXTO TEMPORAL
=============================================================
Hoje é {data_hoje}. Use esta data como referência.
Dica do sistema: Se houver [DATA_INTERPRETADA_PELO_SISTEMA: YYYY-MM-DD] no fim do prompt, isso representa o DIA EXATO.
Para intervalos (ex: "semana que vem", "próximo mês"), você deve calcular o inicio e fim.
"""

def criar_historico_novo():
    """Retorna um histórico limpo com o system prompt injetado."""
    return [{"role": "system", "content": _montar_instrucao_mestre()}]


# -----------------------------------------------------------------------------
# EXECUÇÃO DE UMA TOOL CALL (refatorado - Sprint 7)
# -----------------------------------------------------------------------------
def _executar_tool_call(nome_funcao, args, mensagem_usuario_crua, mensagem_enriquecida,
                        auto_confirmar_gravacao, chat_id):
    """
    Executa UMA chamada de ferramenta já detectada pelo Qwen (ou pelo fallback
    de regex). Retorna a string HTML formatada da resposta.

    Esta função foi extraída das ROTAS 1-8 originais pra permitir que o motor
    processe MÚLTIPLAS tool_calls numa mesma mensagem (ex: "agenda lembrete +
    salva no notion"), sem duplicar código.

    Args:
        nome_funcao: nome da função a chamar (ex: "ferramenta_salvar_notion").
        args: dict com os argumentos já extraídos do tool_call.
        mensagem_usuario_crua: texto original do SDR (pra Blindagem N3).
        mensagem_enriquecida: texto + hint de data (pra fallback de data).
        auto_confirmar_gravacao: bool, se True pula o [Y/n] do terminal.
        chat_id: str opcional, chat alvo das notificações.

    Returns:
        String HTML com o resultado pronto pra enviar ao SDR.
    """
    data_hoje = datetime.now().strftime("%Y-%m-%d")

    # -------------------------------------------------------------------------
    # ROTA 1: LISTAR (COM RANGE DE DATAS + FORMATAÇÃO RICA)
    # -------------------------------------------------------------------------
    if nome_funcao == "ferramenta_listar_notion":
        t_bruto = args.get("tipo")
        s_bruto = args.get("status")
        d_ini_bruto = args.get("data_inicio")
        d_fim_bruto = args.get("data_fim")
        data_legado = args.get("data")

        t_filtro = t_bruto.capitalize() if t_bruto and str(t_bruto).strip() else None
        s_filtro = s_bruto.capitalize() if s_bruto and str(s_bruto).strip() else None
        if s_filtro == "Em Andamento":
            s_filtro = "Em andamento"

        d_ini_filtro = formatar_data_iso(d_ini_bruto) if d_ini_bruto and str(d_ini_bruto).strip() else None
        d_fim_filtro = formatar_data_iso(d_fim_bruto) if d_fim_bruto and str(d_fim_bruto).strip() else None

        if data_legado and not d_ini_filtro and not d_fim_filtro:
            d_legado_formatado = formatar_data_iso(data_legado)
            d_ini_filtro = d_legado_formatado
            d_fim_filtro = d_legado_formatado

        # Chama Notion (novo contrato: list[dict] ou {"erro": ...})
        resultado = listar_itens_no_notion(t_filtro, s_filtro, d_ini_filtro, d_fim_filtro)

        # Formata em HTML estilo bullet denso
        return _formatar_listagem(
            resultado,
            tipo=t_filtro,
            status=s_filtro,
            data_inicio=d_ini_filtro,
            data_fim=d_fim_filtro,
        )

    # -------------------------------------------------------------------------
    # ROTA 2: SALVAR (COM BLINDAGEM NÍVEL 3)
    # -------------------------------------------------------------------------
    elif nome_funcao == "ferramenta_salvar_notion":
        # -----------------------------------------------------------------
        # CAMPO TIPO (precisa ser determinado PRIMEIRO pra guiar extração)
        # -----------------------------------------------------------------
        tipos_validos = {"Lead", "Tarefa", "Nota", "Ideia"}
        tipo_bruto = str(args.get("tipo", "")).strip().capitalize()

        # Se Qwen não deu tipo, inferir da mensagem.
        # ORDEM IMPORTA: tipos semânticos fortes têm prioridade sobre verbos genéricos.
        # "Ideia" e "Nota" são declarados explicitamente pelo SDR — não confundir com ação.
        # "Lead" é identificado por palavras nominais SEM verbos de ação junto.
        # "Tarefa" é o fallback quando há verbos de ação.
        if tipo_bruto not in tipos_validos:
            msg_lower = mensagem_usuario_crua.lower()
            _verbos_acao = ["ligar", "falar", "mandar", "enviar", "agendar", "fazer",
                            "marcar", "tarefa", "organizar", "atualizar", "montar",
                            "chamar", "ligar", "preparar", "revisar", "buscar"]
            _tem_verbo_acao = any(v in msg_lower for v in _verbos_acao)

            if any(v in msg_lower for v in ["ideia", "tive uma ideia", "tenho uma ideia"]):
                # Ideia: prioridade máxima — o SDR declara explicitamente
                tipo_limpo = "Ideia"
            elif any(v in msg_lower for v in ["nota", "anotar", "anota "]):
                # Nota: também declaração explícita
                tipo_limpo = "Nota"
            elif any(v in msg_lower for v in ["lead", "prospect"]) and not _tem_verbo_acao:
                # Lead: palavra nominal clara, sem verbo de ação (ex: "lead João da XP")
                tipo_limpo = "Lead"
            elif _tem_verbo_acao:
                # Há verbos de ação → Tarefa (engloba "fazer proposta pra cliente")
                tipo_limpo = "Tarefa"
            elif any(v in msg_lower for v in ["contato", "cliente"]):
                # Nominais de pessoa sem verbo → provavelmente um Lead
                tipo_limpo = "Lead"
            else:
                tipo_limpo = "Lead"  # default conservador
        else:
            tipo_limpo = tipo_bruto

        # -----------------------------------------------------------------
        # CAMPO NOME (BLINDAGEM NÍVEL 3 - fallback heurístico)
        # -----------------------------------------------------------------
        nome_bruto = args.get("nome") or args.get("nome_do_lead") or ""
        nome_bruto_lower = str(nome_bruto).strip().lower()

        if nome_bruto_lower in NOMES_GENERICOS_SUSPEITOS:
            # Qwen falhou → ativar heurística
            nome_extraido = _extrair_nome_heuristico(mensagem_usuario_crua, tipo_limpo)
            if nome_extraido:
                if DEBUG_EXTRACAO:
                    print(f"⚠️  [BLINDAGEM N3] Nome vazio do Qwen. Extraído por heurística: '{nome_extraido}'")
                nome_limpo = nome_extraido
            else:
                if DEBUG_EXTRACAO:
                    print(f"❌ [BLINDAGEM N3] Heurística falhou. Usando placeholder.")
                nome_limpo = "Entrada sem nome identificado"
        else:
            nome_limpo = str(nome_bruto).strip()

        # -----------------------------------------------------------------
        # CAMPO STATUS
        # -----------------------------------------------------------------
        status_validos = {"Aberto", "Em andamento", "Concluído"}
        status_bruto = str(args.get("status", "")).strip().capitalize()
        if status_bruto == "Em Andamento":
            status_bruto = "Em andamento"
        status_limpo = status_bruto if status_bruto in status_validos else "Aberto"

        # -----------------------------------------------------------------
        # CAMPO DATA (BLINDAGEM N3 - força hint se vier vazio)
        # -----------------------------------------------------------------
        data_do_qwen = args.get("data")

        if not data_do_qwen or not str(data_do_qwen).strip():
            # Qwen mandou data vazia → forçar extração
            data_forcada = _extrair_data_forcada_da_mensagem(mensagem_enriquecida)
            if data_forcada:
                if DEBUG_EXTRACAO:
                    print(f"⚠️  [BLINDAGEM N3] Data vazia do Qwen. Forçada: '{data_forcada}'")
                data_limpa = formatar_data_iso(data_forcada, mensagem_original=mensagem_usuario_crua)
            else:
                data_limpa = data_hoje
        else:
            data_limpa = formatar_data_iso(data_do_qwen, mensagem_original=mensagem_usuario_crua)

        # -----------------------------------------------------------------
        # CAMPO DESCRIÇÃO (BLINDAGEM N3 - fallback heurístico - Passo 5.6)
        # -----------------------------------------------------------------
        desc_bruta = args.get("descricao") or ""
        desc_bruta_lower = str(desc_bruta).strip().lower()

        if desc_bruta_lower in DESCRICOES_GENERICAS:
            # Qwen deixou vazio → ativar heurística
            desc_limpa = _extrair_descricao_heuristica(
                mensagem_usuario_crua, nome_limpo, tipo_limpo
            )
            if DEBUG_EXTRACAO:
                print(f"⚠️  [BLINDAGEM N3] Descrição vazia do Qwen. Heurística gerou: '{desc_limpa}'")
        else:
            desc_limpa = str(desc_bruta).strip()

        if DEBUG_EXTRACAO:
            print(f"✅ [BLINDAGEM N3] Final: nome='{nome_limpo}' | tipo={tipo_limpo} | status={status_limpo} | data={data_limpa}")
            print(f"✅ [BLINDAGEM N3] Descrição final: '{desc_limpa}'")

        if criar_pagina_no_notion(nome_limpo, tipo_limpo, status_limpo, data_limpa, desc_limpa,
                                  auto_confirmar=auto_confirmar_gravacao):
            return _formatar_confirmacao_salvamento(nome_limpo, tipo_limpo, status_limpo, data_limpa)
        else:
            return "❌ Tentei salvar mas a conexão com o Notion falhou ou você cancelou."

    # -------------------------------------------------------------------------
    # ROTA 3: EDITAR (busca por nome + PATCH parcial)
    # -------------------------------------------------------------------------
    elif nome_funcao == "ferramenta_editar_notion":
        # CAMPO nome_busca (obrigatório pra localizar o item)
        nome_busca = str(args.get("nome_busca", "")).strip()
        if not nome_busca:
            nome_busca = _extrair_nome_heuristico(mensagem_usuario_crua, "Lead") or ""

        if not nome_busca:
            return "Não consegui identificar qual item você quer editar. Me diz o nome!"

        resultados = buscar_paginas_por_nome(nome_busca)

        if isinstance(resultados, dict) and "erro" in resultados:
            return f"❌ {resultados['erro']}"

        if len(resultados) == 0:
            return f"Não achei nenhum item com o nome <b>{nome_busca}</b> no Notion. Confere se tá certo?"

        if len(resultados) > 1:
            opcoes = _formatar_opcoes_para_escolha(resultados)
            return (
                f"Achei {len(resultados)} itens com esse nome. Qual você quer editar?\n\n{opcoes}\n\n"
                f"<i>Me manda o nome completo do que você quer mudar.</i>"
            )

        # 1 resultado → monta campos de atualização (só os não-vazios)
        item = resultados[0]
        page_id = item["page_id"]
        campos = {}

        tipos_validos = {"Lead", "Tarefa", "Nota", "Ideia"}
        status_validos = {"Aberto", "Em andamento", "Concluído"}

        novo_nome = str(args.get("novo_nome", "")).strip()
        if novo_nome:
            campos["nome"] = novo_nome

        novo_tipo = str(args.get("novo_tipo", "")).strip().capitalize()
        if novo_tipo in tipos_validos:
            campos["tipo"] = novo_tipo

        novo_status = str(args.get("novo_status", "")).strip().capitalize()
        if novo_status == "Em Andamento":
            novo_status = "Em andamento"
        if novo_status in status_validos:
            campos["status"] = novo_status

        nova_data_bruta = str(args.get("nova_data", "")).strip()
        if nova_data_bruta:
            data_convertida = formatar_data_iso(nova_data_bruta, mensagem_original=mensagem_usuario_crua)
            if data_convertida:
                campos["data"] = data_convertida

        nova_desc = str(args.get("nova_descricao", "")).strip()
        if nova_desc and nova_desc.lower() not in DESCRICOES_GENERICAS:
            campos["descricao"] = nova_desc

        if not campos:
            return "Entendi que você quer editar, mas não identifiquei o que mudar. Me fala o campo e o novo valor!"

        if DEBUG_EXTRACAO:
            print(f"[EDIT] Editando '{item['nome']}' (page_id={page_id}): {campos}")

        if atualizar_pagina_no_notion(page_id, campos):
            return _formatar_confirmacao_edicao(item, campos)
        else:
            return "❌ Não consegui atualizar. Problema de conexão com o Notion."

    # -------------------------------------------------------------------------
    # ROTA 4: EXCLUIR (arquiva no Notion — reversível)
    # Suporta 2 modos:
    #   (a) Pontual: nome_busca → procura 1 item, arquiva.
    #   (b) Em massa: tipo e/ou status → excluir_itens_por_filtro.
    # -------------------------------------------------------------------------
    elif nome_funcao == "ferramenta_excluir_notion":
        tipos_validos = {"Lead", "Tarefa", "Nota", "Ideia"}
        status_validos = {"Aberto", "Em andamento", "Concluído"}

        nome_busca = str(args.get("nome_busca", "")).strip()
        tipo_bulk = str(args.get("tipo", "")).strip().capitalize()
        status_bulk = str(args.get("status", "")).strip().capitalize()
        if status_bulk == "Em Andamento":
            status_bulk = "Em andamento"

        # --- Sanitização do nome_busca ---
        # 1) Remove placeholders de template que o Qwen às vezes alucina
        #    (ex: "{{item.name}}", "{nome}", "<nome>").
        if re.search(r"\{\{.*?\}\}|\{[a-zA-Z_.]+\}|<[a-zA-Z_]+>", nome_busca):
            nome_busca = ""
        # 2) Se o que veio é um token de bulk ("todas", "tudo" etc), trata como vazio
        if nome_busca.lower() in _PALAVRAS_BULK:
            nome_busca = ""

        # --- Inferência BULK a partir da mensagem crua ---
        # Se o SDR falou "todas/tudo" e não pedimos tipo explícito,
        # tentamos inferir o tipo pelo plural presente na mensagem.
        intencao_bulk = _mensagem_tem_intencao_bulk(mensagem_usuario_crua)
        if intencao_bulk and tipo_bulk not in tipos_validos:
            msg_lower = mensagem_usuario_crua.lower()
            if re.search(r"\bideias?\b", msg_lower):
                tipo_bulk = "Ideia"
            elif re.search(r"\btarefas?\b", msg_lower):
                tipo_bulk = "Tarefa"
            elif re.search(r"\bleads?\b|\bprospects?\b", msg_lower):
                tipo_bulk = "Lead"
            elif re.search(r"\bnotas?\b", msg_lower):
                tipo_bulk = "Nota"

        # Também infere status em massa pela mensagem (ex: "remove tudo concluído")
        if intencao_bulk and status_bulk not in status_validos:
            msg_lower = mensagem_usuario_crua.lower()
            if re.search(r"\bconclu[íi]dos?\b|\bfechados?\b|\bfinalizados?\b", msg_lower):
                status_bulk = "Concluído"
            elif re.search(r"\bem\s+andamento\b", msg_lower):
                status_bulk = "Em andamento"
            elif re.search(r"\babertos?\b|\bpendentes?\b", msg_lower):
                status_bulk = "Aberto"

        tem_filtro_bulk = tipo_bulk in tipos_validos or status_bulk in status_validos

        # --- MODO B: EM MASSA por filtro ---
        if tem_filtro_bulk:
            tipo_final = tipo_bulk if tipo_bulk in tipos_validos else None
            status_final = status_bulk if status_bulk in status_validos else None

            if DEBUG_EXTRACAO:
                print(f"[DEL BULK] tipo={tipo_final} status={status_final}")

            resultado_bulk = excluir_itens_por_filtro(tipo=tipo_final, status=status_final)

            if isinstance(resultado_bulk, dict) and "erro" in resultado_bulk:
                return f"❌ {resultado_bulk['erro']}"

            arquivados = resultado_bulk.get("arquivados", [])
            falhas = resultado_bulk.get("falhas", [])
            return _formatar_confirmacao_exclusao_massa(arquivados, falhas,
                                                       tipo=tipo_final,
                                                       status=status_final)

        # --- MODO A: PONTUAL por nome ---
        if not nome_busca:
            # Se há intenção bulk mas não conseguimos inferir tipo/status,
            # pedir desambiguação em vez de chutar.
            if intencao_bulk:
                return (
                    "Entendi que você quer apagar em massa, mas não identifiquei "
                    "o tipo (Lead, Tarefa, Nota, Ideia) nem o status. "
                    "Me diz algo tipo <b>'apague todas as ideias'</b> ou "
                    "<b>'remove tudo que está concluído'</b>."
                )
            # Último recurso: heurística pontual (já guarda contra bulk internamente)
            nome_busca = _extrair_nome_heuristico(mensagem_usuario_crua, "Lead") or ""

        if not nome_busca:
            return "Não consegui identificar qual item excluir. Me diz o nome!"

        resultados = buscar_paginas_por_nome(nome_busca)

        if isinstance(resultados, dict) and "erro" in resultados:
            return f"❌ {resultados['erro']}"

        if len(resultados) == 0:
            return f"Não achei nenhum item com o nome <b>{nome_busca}</b> no Notion."

        if len(resultados) > 1:
            opcoes = _formatar_opcoes_para_escolha(resultados)
            return (
                f"Achei {len(resultados)} itens com esse nome. Qual você quer remover?\n\n{opcoes}\n\n"
                f"<i>Me manda o nome completo do que você quer excluir.</i>"
            )

        item = resultados[0]
        if DEBUG_EXTRACAO:
            print(f"[DEL] Arquivando '{item['nome']}' (page_id={item['page_id']})")

        if excluir_pagina_no_notion(item["page_id"]):
            return _formatar_confirmacao_exclusao(item)
        else:
            return "❌ Não consegui remover. Problema de conexão com o Notion."

    # -------------------------------------------------------------------------
    # ROTA 5: AGENDAR NOTIFICAÇÃO
    # -------------------------------------------------------------------------
    elif nome_funcao == "ferramenta_agendar_notificacao":
        tempo_str = str(args.get("tempo", "")).strip()
        contexto_str = str(args.get("contexto", "")).strip()

        if not tempo_str or not contexto_str:
            return "Não entendi quando ou o que notificar. Me diz o tempo e o que quer ser lembrado!"

        # Interpreta o tempo para datetime absoluto
        dt_disparo = interpretar_tempo_relativo(tempo_str)
        if not dt_disparo:
            return f"Não consegui interpretar o tempo <b>{tempo_str}</b>. Tenta ex: 'em 5 minutos', 'daqui 2 horas', 'às 14h30'."

        disparo_iso = dt_disparo.strftime("%Y-%m-%dT%H:%M:00")
        disparo_humano = formatar_disparo_humano(dt_disparo)

        # Usa chat_id recebido ou fallback para o do .env
        import os
        cid = str(chat_id) if chat_id else os.getenv("TELEGRAM_CHAT_ID", "")

        sucesso, resultado = agendar_notificacao(cid, contexto_str, disparo_iso)

        if sucesso:
            notif_id = resultado.get("id", "?")
            pendentes = len(listar_pendentes())
            disparo_dt_str = dt_disparo.strftime("%d/%m às %H:%M")
            return (
                f"✅ <b>Lembrete agendado!</b>\n\n"
                f"📋 <b>{contexto_str}</b>\n"
                f"🕐 Disparo: <b>{disparo_humano}</b> ({disparo_dt_str})\n"
                f"🆔 ID: <code>{notif_id}</code>\n\n"
                f"<i>{pendentes} lembrete(s) na fila. Use 'meus lembretes' pra ver todos.</i>"
            )
        else:
            return f"❌ Não consegui agendar: {resultado}"

    # -------------------------------------------------------------------------
    # ROTA 6: LISTAR NOTIFICAÇÕES
    # -------------------------------------------------------------------------
    elif nome_funcao == "ferramenta_listar_notificacoes":
        return formatar_lista_notificacoes()

    # -------------------------------------------------------------------------
    # ROTA 7: CANCELAR NOTIFICAÇÃO
    # -------------------------------------------------------------------------
    elif nome_funcao == "ferramenta_cancelar_notificacao":
        id_ou_ctx = str(args.get("id_ou_contexto", "")).strip()
        if not id_ou_ctx:
            return "Me diz o ID ou parte do texto do lembrete que você quer cancelar."

        # Detecta intenção de cancelar TODOS (palavras-chave em massa)
        _PALAVRAS_CANCELAR_TUDO = {"todas", "tudo", "todos", "all", "qualquer", "cada"}
        if id_ou_ctx.lower() in _PALAVRAS_CANCELAR_TUDO:
            pendentes = listar_pendentes()
            if not pendentes:
                return "Não há nenhum lembrete pendente pra cancelar."
            cancelados = []
            for n in pendentes:
                sucesso, _ = cancelar_notificacao(n["id"])
                if sucesso:
                    cancelados.append(n.get("contexto_original", n["id"]))
            if cancelados:
                lista_txt = "\n".join(f"• {c}" for c in cancelados)
                return f"🗑️ {len(cancelados)} lembrete(s) cancelado(s):\n{lista_txt}"
            return "❌ Não consegui cancelar os lembretes. Tenta de novo."

        # Tenta pelo ID primeiro (8 chars alfanumérico)
        if re.match(r"^[a-f0-9]{8}$", id_ou_ctx, re.IGNORECASE):
            sucesso, resultado = cancelar_notificacao(id_ou_ctx)
            if sucesso:
                ctx = resultado.get("contexto_original", "?")
                return f"🗑️ Lembrete cancelado:\n<b>{ctx}</b>"
            else:
                return f"❌ {resultado}"

        # Busca por contexto
        encontrados = buscar_notificacao_por_contexto(id_ou_ctx)
        if not encontrados:
            return f"Não achei nenhum lembrete pendente com o texto <b>{id_ou_ctx}</b>."
        if len(encontrados) > 1:
            lista = formatar_lista_notificacoes(encontrados)
            return f"Achei {len(encontrados)} lembretes com esse texto. Qual cancelar? Me manda o ID:\n\n{lista}"
        sucesso, resultado = cancelar_notificacao(encontrados[0]["id"])
        if sucesso:
            ctx = resultado.get("contexto_original", "?")
            return f"🗑️ Lembrete cancelado:\n<b>{ctx}</b>"
        else:
            return f"❌ {resultado}"

    # -------------------------------------------------------------------------
    # ROTA 8: EDITAR NOTIFICAÇÃO
    # -------------------------------------------------------------------------
    elif nome_funcao == "ferramenta_editar_notificacao":
        id_ou_ctx = str(args.get("id_ou_contexto", "")).strip()
        novo_tempo_str = str(args.get("novo_tempo", "")).strip()
        novo_contexto_str = str(args.get("novo_contexto", "")).strip()

        if not id_ou_ctx:
            return "Me diz o ID ou parte do texto do lembrete que você quer editar."
        if not novo_tempo_str and not novo_contexto_str:
            return "O que você quer mudar? Me diz o novo horário ou o novo texto do lembrete."

        # Resolve novo tempo se fornecido
        novo_tempo_iso = None
        novo_disparo_humano = ""
        if novo_tempo_str:
            dt_novo = interpretar_tempo_relativo(novo_tempo_str)
            if not dt_novo:
                return f"Não consegui interpretar o novo horário <b>{novo_tempo_str}</b>."
            novo_tempo_iso = dt_novo.strftime("%Y-%m-%dT%H:%M:00")
            novo_disparo_humano = formatar_disparo_humano(dt_novo)

        # Localiza a notificação
        if re.match(r"^[a-f0-9]{8}$", id_ou_ctx, re.IGNORECASE):
            notif_id = id_ou_ctx
        else:
            encontrados = buscar_notificacao_por_contexto(id_ou_ctx)
            if not encontrados:
                return f"Não achei nenhum lembrete pendente com o texto <b>{id_ou_ctx}</b>."
            if len(encontrados) > 1:
                lista = formatar_lista_notificacoes(encontrados)
                return f"Achei {len(encontrados)} lembretes. Qual editar? Me manda o ID:\n\n{lista}"
            notif_id = encontrados[0]["id"]

        sucesso, resultado = editar_notificacao(
            notif_id,
            novo_tempo_iso=novo_tempo_iso,
            novo_contexto=novo_contexto_str or None,
        )
        if sucesso:
            ctx = resultado.get("contexto_original", "?")
            linhas = [f"✏️ Lembrete atualizado:\n<b>{ctx}</b>"]
            if novo_disparo_humano:
                disparo_dt_str = datetime.fromisoformat(resultado["disparo_em"]).strftime("%d/%m às %H:%M")
                linhas.append(f"🕐 Novo horário: <b>{novo_disparo_humano}</b> ({disparo_dt_str})")
            if novo_contexto_str:
                linhas.append(f"📋 Novo texto: <b>{novo_contexto_str}</b>")
            return "\n".join(linhas)
        else:
            return f"❌ {resultado}"

    # -------------------------------------------------------------------------
    # Função desconhecida (não deveria chegar aqui)
    # -------------------------------------------------------------------------
    return f"❌ Função desconhecida: {nome_funcao}"


# -----------------------------------------------------------------------------
# MOTOR PURO - processa uma mensagem e retorna a resposta
# -----------------------------------------------------------------------------
def processar_mensagem(mensagem_usuario_crua, historico, auto_confirmar_gravacao=False, chat_id=None):
    """
    Motor de raciocínio do Trembinho, desacoplado de qualquer interface.

    Sprint 8 — mudanças:
      1. Blindagem N4 substituída por validação estrutural pura.
         Não há mais lista de regex de alucinação (GATILHOS_ALUCINACAO).
         A prevenção ocorre no prompt (personalidade v9).
      2. Se msg.tool_calls é None e o content não é JSON residual,
         a resposta é considerada conversacional e retornada diretamente.
    """
    mensagem_enriquecida = _enriquecer_mensagem_com_data(mensagem_usuario_crua)
    historico.append({"role": "user", "content": mensagem_enriquecida})

    # Retry com backoff para recuperar de quedas momentâneas do Ollama
    _OLLAMA_MAX_TENTATIVAS = 3
    _OLLAMA_BACKOFF = 3  # segundos entre tentativas

    import time as _time
    ultimo_erro = None
    for _tentativa in range(1, _OLLAMA_MAX_TENTATIVAS + 1):
        try:
            resposta = ollama.chat(
                model=MODELO_LOCAL,
                messages=historico,
                tools=[
                    ferramenta_salvar_notion,
                    ferramenta_listar_notion,
                    ferramenta_editar_notion,
                    ferramenta_excluir_notion,
                    ferramenta_agendar_notificacao,
                    ferramenta_listar_notificacoes,
                    ferramenta_cancelar_notificacao,
                    ferramenta_editar_notificacao,
                ],
                options=OPCOES_OLLAMA,
            )
            ultimo_erro = None
            break  # sucesso — sai do loop de retry
        except Exception as e:
            ultimo_erro = e
            eh_erro_conexao = any(kw in str(e).lower() for kw in [
                "connection", "connect", "ollama", "refused", "timeout", "unreachable"
            ])
            if eh_erro_conexao and _tentativa < _OLLAMA_MAX_TENTATIVAS:
                print(f"[OLLAMA] Tentativa {_tentativa} falhou ({e}). Aguardando {_OLLAMA_BACKOFF}s...")
                _time.sleep(_OLLAMA_BACKOFF)
                continue
            # Erro não-conexão ou última tentativa — sai imediatamente
            break

    if ultimo_erro is not None:
        eh_conexao = any(kw in str(ultimo_erro).lower() for kw in [
            "connection", "connect", "ollama", "refused", "timeout", "unreachable"
        ])
        if eh_conexao:
            return (
                "⚠️ <b>Motor local offline.</b>\n\n"
                "O Ollama não está respondendo. Para religar:\n"
                "1. Abra o <b>Ollama</b> no seu computador\n"
                "2. Aguarde aparecer o ícone na bandeja do sistema\n"
                "3. Mande qualquer mensagem aqui pra testar\n\n"
                "<i>Seus dados no Notion estão seguros — só o motor de IA precisa ser reiniciado.</i>",
                historico,
            )
        return (f"❌ Erro no motor local: {ultimo_erro}", historico)

    try:
        msg = resposta.message
        historico.append(msg)

        # ---------------------------------------------------------------------
        # COLETA DE TOOL CALLS — suporta N chamadas por mensagem (Sprint 7)
        # ---------------------------------------------------------------------
        tool_calls_a_executar = []  # lista de tuplas (nome_funcao, args)

        if msg.tool_calls:
            # Caminho feliz: o Qwen usou o mecanismo nativo de tool calling.
            # Pega TODAS as chamadas — não só a [0].
            for tc in msg.tool_calls:
                nome = tc.function.name
                args = tc.function.arguments
                # Aceita só funções válidas (evita alucinação de nome)
                if nome in FUNCOES_VALIDAS:
                    tool_calls_a_executar.append((nome, args))
                elif DEBUG_EXTRACAO:
                    print(f"⚠️  [SANIDADE] Função inválida ignorada: '{nome}'")
        else:
            # Fallback: o Qwen vazou JSON no content em vez de usar tool_call.
            # Tenta detectar via regex (comportamento de segurança — 1 match só).
            match_salvar = re.search(r'\{.*"nome".*\}', msg.content or "", re.DOTALL)
            match_listar = re.search(r'\{.*"tipo".*\}', msg.content or "", re.DOTALL)
            match_editar = re.search(r'\{.*"nome_busca".*\}', msg.content or "", re.DOTALL)
            match_excluir = re.search(r'ferramenta_excluir_notion', msg.content or "")

            if match_excluir and match_editar:
                try:
                    args = json.loads(match_editar.group(0))
                    tool_calls_a_executar.append(("ferramenta_excluir_notion", args))
                except json.JSONDecodeError:
                    pass
            elif match_editar:
                try:
                    args = json.loads(match_editar.group(0))
                    tool_calls_a_executar.append(("ferramenta_editar_notion", args))
                except json.JSONDecodeError:
                    pass
            elif match_salvar:
                try:
                    args = json.loads(match_salvar.group(0))
                    tool_calls_a_executar.append(("ferramenta_salvar_notion", args))
                except json.JSONDecodeError:
                    pass
            elif match_listar:
                try:
                    args = json.loads(match_listar.group(0))
                    tool_calls_a_executar.append(("ferramenta_listar_notion", args))
                except json.JSONDecodeError:
                    pass

        # Deduplica tool_calls — Qwen às vezes retorna N chamadas idênticas
        _seen_tc = set()
        _deduped = []
        for _nome, _args in tool_calls_a_executar:
            _key = (_nome, json.dumps(_args, sort_keys=True, default=str))
            if _key not in _seen_tc:
                _seen_tc.add(_key)
                _deduped.append((_nome, _args))
        tool_calls_a_executar = _deduped

        # ---------------------------------------------------------------------
        # EXECUTA TODAS AS TOOL CALLS ENFILEIRADAS
        # ---------------------------------------------------------------------
        if tool_calls_a_executar:
            respostas = []
            for nome_funcao, args in tool_calls_a_executar:
                if DEBUG_EXTRACAO:
                    print(f"\n🔍 [DEBUG] Função detectada: {nome_funcao}")
                    print(f"🔍 [DEBUG] Args crus do Qwen: {args}")
                resposta_txt = _executar_tool_call(
                    nome_funcao, args,
                    mensagem_usuario_crua, mensagem_enriquecida,
                    auto_confirmar_gravacao, chat_id,
                )
                respostas.append(resposta_txt)

            # Concatena respostas quando houver múltiplas tool calls
            return ("\n\n".join(respostas), historico)

        # ---------------------------------------------------------------------
        # BLINDAGEM NÍVEL 4 — Validação estrutural (Sprint 8)
        # ---------------------------------------------------------------------
        # Se chegou aqui: sem tool_calls nativos, sem JSON detectado no fallback.
        # Com o prompt v9, isso indica resposta conversacional legítima.
        # Único edge case tratado: content que começa com "{" mas escapou o
        # fallback parser acima (JSON malformado ou incompleto).
        conteudo = msg.content or ""

        if not conteudo.strip():
            return ("Hmm, não entendi. Pode repetir?", historico)

        if conteudo.strip().startswith("{"):
            if DEBUG_EXTRACAO:
                print(f"[BLINDAGEM N4] JSON residual no content, não processado: {conteudo[:100]}")
            return (
                "⚠️ Não consegui processar sua solicitação. Pode repetir de forma mais direta?",
                historico,
            )

        # Resposta conversacional legítima — retorna direto
        return (conteudo, historico)

    except Exception as e:
        return (f"❌ Erro no motor local: {e}", historico)


# -----------------------------------------------------------------------------
# Loop de terminal (casca fina - apenas UI)
# -----------------------------------------------------------------------------
def rodar_agente(chave_gemini=None):
    print("✅ Motor local otimizado (Qwen 14B - Pipeline Listar Range v2.5).")
    print("💬 Pode falar naturalmente. Digite 'sair' para encerrar.")
    print("-" * 50)

    historico = criar_historico_novo()

    while True:
        mensagem_usuario_crua = input("\n🙋 Você: ").strip()
        if not mensagem_usuario_crua or mensagem_usuario_crua.lower() in COMANDOS_DE_SAIDA:
            break

        print("\n⏳ [SISTEMA] Processando...")

        resposta, historico = processar_mensagem(mensagem_usuario_crua, historico)

        print(f"\n🤖 Trembinho: {resposta}")
