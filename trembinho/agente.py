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
"""

import ollama
import json
import re
from datetime import datetime
from trembinho.personalidade import PERSONALIDADE_TREMBINHO
from trembinho.notion import criar_pagina_no_notion, listar_itens_no_notion
from trembinho.datas import interpretar_data

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
            r"(?:é\s+)?(ligar|falar|mandar|enviar|agendar|fazer|marcar|buscar|responder|preparar|estudar|revisar)\s+"
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
# MOTOR PURO - processa uma mensagem e retorna a resposta
# -----------------------------------------------------------------------------
def processar_mensagem(mensagem_usuario_crua, historico, auto_confirmar_gravacao=False):
    """
    Motor de raciocínio do Trembinho, desacoplado de qualquer interface.
    """
    data_hoje = datetime.now().strftime("%Y-%m-%d")
    mensagem_enriquecida = _enriquecer_mensagem_com_data(mensagem_usuario_crua)
    historico.append({"role": "user", "content": mensagem_enriquecida})

    try:
        resposta = ollama.chat(
            model=MODELO_LOCAL,
            messages=historico,
            tools=[ferramenta_salvar_notion, ferramenta_listar_notion],
            options=OPCOES_OLLAMA,
        )

        msg = resposta.message
        historico.append(msg)

        # ---------------------------------------------------------------------
        # Roteamento e Blindagem Nível 2
        # ---------------------------------------------------------------------
        args = None
        nome_funcao = None

        if msg.tool_calls:
            nome_funcao = msg.tool_calls[0].function.name
            args = msg.tool_calls[0].function.arguments
        else:
            match_salvar = re.search(r'\{.*"nome".*\}', msg.content or "", re.DOTALL)
            match_listar = re.search(r'\{.*"tipo".*\}', msg.content or "", re.DOTALL)

            if match_salvar:
                try:
                    args = json.loads(match_salvar.group(0))
                    nome_funcao = "ferramenta_salvar_notion"
                except json.JSONDecodeError:
                    pass
            elif match_listar:
                try:
                    args = json.loads(match_listar.group(0))
                    nome_funcao = "ferramenta_listar_notion"
                except json.JSONDecodeError:
                    pass

        # ---------------------------------------------------------------------
        # DEBUG DE EXTRAÇÃO (temporário - Passo 5.5)
        # ---------------------------------------------------------------------
        if DEBUG_EXTRACAO and args is not None:
            print(f"\n🔍 [DEBUG] Função detectada: {nome_funcao}")
            print(f"🔍 [DEBUG] Args crus do Qwen: {args}")

        if args is not None and nome_funcao:

            # ROTA 1: LISTAR (COM RANGE DE DATAS + FORMATAÇÃO RICA)
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
                texto_formatado = _formatar_listagem(
                    resultado,
                    tipo=t_filtro,
                    status=s_filtro,
                    data_inicio=d_ini_filtro,
                    data_fim=d_fim_filtro,
                )
                return (texto_formatado, historico)

            # ROTA 2: SALVAR (COM BLINDAGEM NÍVEL 3)
            elif nome_funcao == "ferramenta_salvar_notion":
                # -----------------------------------------------------------------
                # CAMPO TIPO (precisa ser determinado PRIMEIRO pra guiar extração)
                # -----------------------------------------------------------------
                tipos_validos = {"Lead", "Tarefa", "Nota", "Ideia"}
                tipo_bruto = str(args.get("tipo", "")).strip().capitalize()
                
                # Se Qwen não deu tipo, inferir da mensagem
                if tipo_bruto not in tipos_validos:
                    msg_lower = mensagem_usuario_crua.lower()
                    if any(v in msg_lower for v in ["ligar", "falar", "mandar", "enviar", "agendar", "fazer", "marcar", "tarefa"]):
                        tipo_limpo = "Tarefa"
                    elif any(v in msg_lower for v in ["lead", "contato", "prospect", "cliente"]):
                        tipo_limpo = "Lead"
                    elif any(v in msg_lower for v in ["nota", "anotar "]):
                        tipo_limpo = "Nota"
                    elif "ideia" in msg_lower:
                        tipo_limpo = "Ideia"
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
                    return (
                        _formatar_confirmacao_salvamento(nome_limpo, tipo_limpo, status_limpo, data_limpa),
                        historico,
                    )
                else:
                    return ("❌ Tentei salvar mas a conexão falhou ou você cancelou.", historico)

        # Conversa normal (sem tool call)
        return (msg.content or "", historico)

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