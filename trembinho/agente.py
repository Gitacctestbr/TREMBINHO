"""
TREMBINHO - Motor do Agente (Claude Sonnet 4.6 via API Anthropic)
==================================================================
Foco: assertividade, interpretação de linguagem natural e Blindagem Nível 3/4.
ALTERAÇÃO: Implementada Janela de Contexto para controle de custos de API.
"""

import json
import re
import requests
import os
import time as _time
from datetime import datetime
from dotenv import load_dotenv
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

load_dotenv()
CHAVE_ANTHROPIC = os.getenv("ANTHROPIC_API_KEY")
if not CHAVE_ANTHROPIC:
    raise ValueError("⚠️  ANTHROPIC_API_KEY não encontrada no .env. Configure a chave antes de rodar.")

URL_API_CLAUDE = "https://api.anthropic.com/v1/messages"
MODELO_CLAUDE = "claude-haiku-4-5-20251001"
COMANDOS_DE_SAIDA = ["sair", "exit", "quit", "fechar"]

DEBUG_EXTRACAO = False

OPCOES_CLAUDE = {
    "temperature": 0.3,
    "max_tokens": 1024,
}

NOMES_GENERICOS_SUSPEITOS = {
    "", "nova entrada", "lead novo", "tarefa nova", "nota nova",
    "sem nome", "n/a", "nova tarefa", "novo lead", "entrada", "item",
    "none", "null",
}

DESCRICOES_GENERICAS = {
    "", "none", "null", "n/a", "-", "vazio",
}

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

def ferramenta_salvar_notion(nome: str, tipo: str, status: str, data: str, descricao: str) -> bool:
    pass

def ferramenta_listar_notion(tipo: str = None, status: str = None, data_inicio: str = None, data_fim: str = None) -> bool:
    pass

def ferramenta_excluir_notion(nome_busca: str = "", tipo: str = "", status: str = "") -> bool:
    pass

def ferramenta_agendar_notificacao(tempo: str, contexto: str) -> bool:
    pass

def ferramenta_listar_notificacoes() -> bool:
    pass

def ferramenta_cancelar_notificacao(id_ou_contexto: str) -> bool:
    pass

def ferramenta_editar_notificacao(id_ou_contexto: str, novo_tempo: str = "", novo_contexto: str = "") -> bool:
    pass

def ferramenta_editar_notion(nome_busca: str, novo_nome: str = "", novo_tipo: str = "", novo_status: str = "", nova_data: str = "", nova_descricao: str = "") -> bool:
    pass

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

_PALAVRAS_BULK = {"todas", "todos", "tudo", "todinhos", "todinhas", "cada", "qualquer", "quaisquer", "all"}

def _mensagem_tem_intencao_bulk(mensagem_original):
    if not mensagem_original: return False
    txt = mensagem_original.lower()
    return any(re.search(rf"\b{re.escape(p)}\b", txt) for p in _PALAVRAS_BULK)

def _extrair_nome_heuristico(mensagem_original, tipo_inferido):
    if not mensagem_original: return None
    if _mensagem_tem_intencao_bulk(mensagem_original): return None
    texto = mensagem_original.strip()
    if tipo_inferido == "Lead":
        padroes_lead = [
            r"(?:pra|para)\s+([A-ZÁÉÍÓÚÃÕÂÊÎÔÛÇ][\wáéíóúãõâêîôûç]+(?:\s+[A-ZÁÉÍÓÚÃÕÂÊÎÔÛÇ]?[\wáéíóúãõâêîôûç]+){0,3})",
            r"(?:lead|contato|prospect|cliente)\s+([A-ZÁÉÍÓÚÃÕÂÊÎÔÛÇ][\wáéíóúãõâêîôûç]+(?:\s+[A-ZÁÉÍÓÚÃÕÂÊÎÔÛÇ]?[\wáéíóúãõâêîôûç]+){0,3})",
            r"(?:o|a|do|da)\s+([A-ZÁÉÍÓÚÃÕÂÊÎÔÛÇ][\wáéíóúãõâêîôûç]+(?:\s+[A-ZÁÉÍÓÚÃÕÂÊÎÔÛÇ]?[\wáéíóúãõâêîôûç]+){0,2})",
        ]
        for padrao in padroes_lead:
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                candidato = match.group(1).strip()
                return " ".join(w.capitalize() for w in candidato.split())
        match_cap = re.search(r"\b([A-ZÁÉÍÓÚÃÕÂÊÎÔÛÇ][a-záéíóúãõâêîôûç]{2,})\b", texto)
        if match_cap: return match_cap.group(1)
    if tipo_inferido == "Tarefa":
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
    if not mensagem_original: return None
    match_hint = re.search(r"\[DATA_INTERPRETADA_PELO_SISTEMA:\s*([^\]]+)\]", mensagem_original)
    if match_hint: return match_hint.group(1).strip()
    return interpretar_data(mensagem_original)

def _extrair_descricao_heuristica(mensagem_original, nome_extraido, tipo_inferido):
    if not mensagem_original: return _descricao_default_por_tipo(tipo_inferido)
    texto = mensagem_original.strip()
    texto = re.sub(r"\[DATA_INTERPRETADA_PELO_SISTEMA:[^\]]+\]", "", texto)
    texto = re.sub(r"^(salva|salve|anota|anote|registra|registre|joga\s+a[íi]|adiciona|adicione|cria|crie|marca|marque|cadastra|cadastre|bota|bote|coloca|coloque|da\s+um\s+salve|dá\s+um\s+salve)\s+", "", texto, flags=re.IGNORECASE)
    padroes_data_hora = [r"\b(hoje|amanh[ãa]|ontem|depois\s+de\s+amanh[ãa])\b", r"\b(pr[óo]xim[ao]\s+|essa\s+|esta\s+)?(segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo)(-feira)?(\s+que\s+vem)?\b", r"\b[àa]s?\s+\d{1,2}[:h]\d{0,2}\b", r"\b\d{1,2}[:h]\d{2}\b", r"\b\d{1,2}h\b", r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", r"\bdaqui\s+a?\s*\d+\s+(dia|dias|semana|semanas|m[eê]s|m[eê]ses)\b", r"\bem\s+\d+\s+(dia|dias|semana|semanas|m[eê]s|m[eê]ses)\b", r"\bpr[ao]\s+(?=amanh[ãa]|hoje|segunda|ter[çc]a|quarta|quinta|sexta)"]
    for padrao in padroes_data_hora: texto = re.sub(padrao, "", texto, flags=re.IGNORECASE)
    if nome_extraido:
        texto = re.sub(re.escape(nome_extraido), "", texto, flags=re.IGNORECASE)
        for parte in nome_extraido.split():
            if len(parte) > 3: texto = re.sub(rf"\b{re.escape(parte)}\b", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\b(lead|contato|prospect|cliente|tarefa|nota|ideia|pra|para|pro|de|do|da|o|a|um|uma|que|é|eu|mim|com|no|na)\b", " ", texto, flags=re.IGNORECASE)
    texto = re.sub(r"[,;:\s]+", " ", texto).strip(" .,;:-")
    if len(texto) >= 8:
        texto = texto[0].upper() + texto[1:]
        if not texto.endswith("."): texto += "."
        return texto
    return _descricao_default_por_tipo(tipo_inferido)

def _descricao_default_por_tipo(tipo):
    defaults = {"Lead": "Lead prospectado via Trembinho.", "Tarefa": "Tarefa registrada via Trembinho.", "Nota": "Nota rápida via Trembinho.", "Ideia": "Ideia capturada via Trembinho."}
    return defaults.get(tipo, "Registrado via Trembinho.")

EMOJI_TIPO = {"Lead": "👤", "Tarefa": "📞", "Nota": "📝", "Ideia": "💡"}
EMOJI_STATUS = {"Aberto": "🟢", "Em andamento": "🟡", "Concluído": "✅"}
MESES_ABREV = {1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun", 7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez"}

def _formatar_data_humana(data_iso):
    if not data_iso or data_iso == "Sem data": return "sem data"
    s = str(data_iso).strip()
    if "T" in s:
        parte_data, parte_hora = s.split("T", 1)
        parte_hora = re.split(r"[+\-Z]", parte_hora)[0].split(".")[0]
        hora_str = ":".join(parte_hora.split(":")[:2]) if ":" in parte_hora else ""
    else:
        parte_data, hora_str = s, ""
    try:
        dt = datetime.strptime(parte_data, "%Y-%m-%d")
        data_legivel = f"{dt.day:02d}/{MESES_ABREV[dt.month]}"
    except: return s
    return f"{data_legivel} {hora_str}".strip() if hora_str and hora_str != "00:00" else data_legivel

def _formatar_cabecalho_filtros(tipo, status, data_inicio, data_fim):
    partes = [{"Lead": "Leads", "Tarefa": "Tarefas", "Nota": "Notas", "Ideia": "Ideias"}.get(tipo, tipo)] if tipo else ["Pipeline"]
    if status: partes.append(status)
    hoje_str = datetime.now().strftime("%Y-%m-%d")
    if data_inicio and data_fim:
        d_ini, d_fim = data_inicio.split("T")[0], data_fim.split("T")[0]
        partes.append("hoje" if d_ini == d_fim == hoje_str else (_formatar_data_humana(d_ini) if d_ini == d_fim else f"{_formatar_data_humana(d_ini)} → {_formatar_data_humana(d_fim)}"))
    elif data_inicio: partes.append(f"desde {_formatar_data_humana(data_inicio)}")
    elif data_fim: partes.append(f"até {_formatar_data_humana(data_fim)}")
    return f"🎯 <b>{' • '.join(partes)}</b>"

def _formatar_listagem(itens, tipo=None, status=None, data_inicio=None, data_fim=None):
    if isinstance(itens, dict) and "erro" in itens: return f"❌ {itens['erro']}"
    cabecalho = _formatar_cabecalho_filtros(tipo, status, data_inicio, data_fim)
    if not itens: return f"{cabecalho}\n\n<i>Nada por aqui. Campo limpo. 🧹</i>"
    linhas = [f"• {EMOJI_TIPO.get(item.get('tipo'), '•')} {item.get('nome', 'Sem título')} — 📅 {_formatar_data_humana(item.get('data'))} {EMOJI_STATUS.get(item.get('status'), '')}".rstrip() for item in itens]
    return f"{cabecalho}\n\n" + "\n".join(linhas) + f"\n\n<i>{len(itens)} {'item' if len(itens) == 1 else 'itens'}</i>"

def _formatar_confirmacao_salvamento(nome, tipo, status, data_iso):
    return f"✅ <b>{tipo}</b> salva no pipeline:\n<b>{nome}</b>\n📅 {_formatar_data_humana(data_iso)} {EMOJI_STATUS.get(status, '')} {status}"

def _formatar_confirmacao_edicao(item, campos_alterados):
    status_f, data_f = campos_alterados.get("status") or item.get("status", "?"), campos_alterados.get("data") or item.get("data", "")
    return f"✏️ <b>{item.get('tipo', '?')}</b> atualizado:\n<b>{item.get('nome', '?')}</b>\n📅 {_formatar_data_humana(data_f)} {EMOJI_STATUS.get(status_f, '')} {status_f}\n<i>Campos alterados: {', '.join(campos_alterados.keys())}</i>"

def _formatar_confirmacao_exclusao(item):
    return f"🗑️ {EMOJI_TIPO.get(item.get('tipo'), '•')} <b>{item.get('nome', '?')}</b> removido do pipeline.\n<i>(Arquivado no Notion)</i>"

def _formatar_confirmacao_exclusao_massa(arquivados, falhas, tipo=None, status=None):
    total_ok, total_falhou = len(arquivados), len(falhas)
    partes_f = []
    if tipo: partes_f.append({"Lead": "Leads", "Tarefa": "Tarefas", "Nota": "Notas", "Ideia": "Ideias"}.get(tipo, tipo))
    if status: partes_f.append(status)
    filtro_txt = " • ".join(partes_f) if partes_f else "itens"
    if total_ok == 0 and total_falhou == 0: return f"<i>Nenhum item encontrado com filtro <b>{filtro_txt}</b>.</i>"
    linhas = [f"🗑️ <b>Exclusão em massa — {filtro_txt}</b>", ""]
    if arquivados:
        for item in arquivados: linhas.append(f"• {EMOJI_TIPO.get(item.get('tipo'), '•')} {item.get('nome', '?')}")
    linhas.append(f"\n<i>{total_ok} item(s) arquivado(s).</i>")
    return "\n".join(linhas)

def _formatar_opcoes_para_escolha(resultados):
    return "\n".join([f"{i}. {EMOJI_TIPO.get(item.get('tipo'), '•')} <b>{item.get('nome', '?')}</b> — {item.get('tipo', '?')} — {_formatar_data_humana(item.get('data'))} {EMOJI_STATUS.get(item.get('status'), '')}" for i, item in enumerate(resultados, 1)])

def _montar_instrucao_mestre():
    data_hoje = datetime.now().strftime("%Y-%m-%d")
    return f"""{PERSONALIDADE_TREMBINHO}\n\nCONTEXTO TEMPORAL: Hoje é {data_hoje}."""

def criar_historico_novo(): return []

def _construir_tools_schema():
    return [
        {"name": "ferramenta_salvar_notion", "description": "Salva uma entrada no Notion.", "input_schema": {"type": "object", "properties": {"nome": {"type": "string"}, "tipo": {"type": "string", "enum": ["Lead", "Tarefa", "Nota", "Ideia"]}, "status": {"type": "string", "enum": ["Aberto", "Em andamento", "Concluído"]}, "data": {"type": "string"}, "descricao": {"type": "string"}}, "required": ["nome", "tipo", "status", "data", "descricao"]}},
        {"name": "ferramenta_listar_notion", "description": "Lista itens do Notion.", "input_schema": {"type": "object", "properties": {"tipo": {"type": "string", "enum": ["Lead", "Tarefa", "Nota", "Ideia"]}, "status": {"type": "string", "enum": ["Aberto", "Em andamento", "Concluído"]}, "data_inicio": {"type": "string"}, "data_fim": {"type": "string"}}, "required": []}},
        {"name": "ferramenta_editar_notion", "description": "Edita uma entrada.", "input_schema": {"type": "object", "properties": {"nome_busca": {"type": "string"}, "novo_nome": {"type": "string"}, "novo_tipo": {"type": "string", "enum": ["Lead", "Tarefa", "Nota", "Ideia"]}, "novo_status": {"type": "string", "enum": ["Aberto", "Em andamento", "Concluído"]}, "nova_data": {"type": "string"}, "nova_descricao": {"type": "string"}}, "required": ["nome_busca"]}},
        {"name": "ferramenta_excluir_notion", "description": "Remove entradas.", "input_schema": {"type": "object", "properties": {"nome_busca": {"type": "string"}, "tipo": {"type": "string", "enum": ["Lead", "Tarefa", "Nota", "Ideia"]}, "status": {"type": "string", "enum": ["Aberto", "Em andamento", "Concluído"]}}, "required": []}},
        {"name": "ferramenta_agendar_notificacao", "description": "Agenda notificação.", "input_schema": {"type": "object", "properties": {"tempo": {"type": "string"}, "contexto": {"type": "string"}}, "required": ["tempo", "contexto"]}},
        {"name": "ferramenta_listar_notificacoes", "description": "Lista lembretes.", "input_schema": {"type": "object", "properties": {}, "required": []}},
        {"name": "ferramenta_cancelar_notificacao", "description": "Cancela lembrete.", "input_schema": {"type": "object", "properties": {"id_ou_contexto": {"type": "string"}}, "required": ["id_ou_contexto"]}},
        {"name": "ferramenta_editar_notificacao", "description": "Edita lembrete.", "input_schema": {"type": "object", "properties": {"id_ou_contexto": {"type": "string"}, "novo_tempo": {"type": "string"}, "novo_contexto": {"type": "string"}}, "required": ["id_ou_contexto"]}, "cache_control": {"type": "ephemeral"}},
    ]

def _executar_tool_call(nome_funcao, args, mensagem_usuario_crua, mensagem_enriquecida, auto_confirmar_gravacao, chat_id):
    data_hoje = datetime.now().strftime("%Y-%m-%d")
    if nome_funcao == "ferramenta_listar_notion":
        t, s = str(args.get("tipo", "")).capitalize(), str(args.get("status", "")).capitalize()
        if s == "Em Andamento": s = "Em andamento"
        d_ini = formatar_data_iso(args["data_inicio"]) if args.get("data_inicio") else None
        d_fim = formatar_data_iso(args["data_fim"]) if args.get("data_fim") else None
        res = listar_itens_no_notion(t or None, s or None, d_ini, d_fim)
        return _formatar_listagem(res, t or None, s or None, d_ini, d_fim)
    elif nome_funcao == "ferramenta_salvar_notion":
        tipo_l = str(args.get("tipo", "")).capitalize()
        nome_l = str(args.get("nome", "")).strip()
        if nome_l.lower() in NOMES_GENERICOS_SUSPEITOS: nome_l = _extrair_nome_heuristico(mensagem_usuario_crua, tipo_l) or "Entrada sem nome"
        status_l = str(args.get("status", "")).capitalize()
        if status_l == "Em Andamento": status_l = "Em andamento"
        data_l = formatar_data_iso(args.get("data") or _extrair_data_forcada_da_mensagem(mensagem_enriquecida))
        desc_l = str(args.get("descricao", "")).strip()
        if desc_l.lower() in DESCRICOES_GENERICAS: desc_l = _extrair_descricao_heuristica(mensagem_usuario_crua, nome_l, tipo_l)
        if criar_pagina_no_notion(nome_l, tipo_l, status_l, data_l, desc_l, auto_confirmar=auto_confirmar_gravacao):
            return _formatar_confirmacao_salvamento(nome_l, tipo_l, status_l, data_l)
        return "❌ Erro ao salvar no Notion."
    elif nome_funcao == "ferramenta_editar_notion":
        n_busca = str(args.get("nome_busca", "")).strip() or _extrair_nome_heuristico(mensagem_usuario_crua, "Lead")
        res = buscar_paginas_por_nome(n_busca)
        if not res: return f"Não achei <b>{n_busca}</b>."
        if len(res) > 1: return f"Achei vários. Qual editar?\n\n{_formatar_opcoes_para_escolha(res)}"
        item, campos = res[0], {}
        if args.get("novo_nome"): campos["nome"] = args["novo_nome"]
        if args.get("novo_status"): campos["status"] = args["novo_status"]
        if args.get("nova_data"): campos["data"] = formatar_data_iso(args["nova_data"])
        if args.get("nova_descricao"): campos["descricao"] = args["nova_descricao"]
        if atualizar_pagina_no_notion(item["page_id"], campos): return _formatar_confirmacao_edicao(item, campos)
        return "❌ Erro ao editar."
    elif nome_funcao == "ferramenta_excluir_notion":
        n_busca, t_b, s_b = str(args.get("nome_busca", "")).strip(), str(args.get("tipo", "")).capitalize(), str(args.get("status", "")).capitalize()
        if t_b or s_b:
            res_b = excluir_itens_por_filtro(tipo=t_b or None, status=s_b or None)
            return _formatar_confirmacao_exclusao_massa(res_b.get("arquivados", []), res_b.get("falhas", []), t_b, s_b)
        res = buscar_paginas_por_nome(n_busca)
        if not res: return f"Não achei <b>{n_busca}</b>."
        if excluir_pagina_no_notion(res[0]["page_id"]): return _formatar_confirmacao_exclusao(res[0])
        return "❌ Erro ao excluir."
    elif nome_funcao == "ferramenta_agendar_notificacao":
        dt = interpretar_tempo_relativo(args.get("tempo", ""))
        if not dt: return "Não entendi o tempo."
        cid = str(chat_id) if chat_id else os.getenv("TELEGRAM_CHAT_ID", "")
        sucesso, res = agendar_notificacao(cid, args.get("contexto", ""), dt.strftime("%Y-%m-%dT%H:%M:00"))
        return f"✅ Lembrete agendado para {formatar_disparo_humano(dt)}!" if sucesso else f"❌ {res}"
    elif nome_funcao == "ferramenta_listar_notificacoes": return formatar_lista_notificacoes()
    elif nome_funcao == "ferramenta_cancelar_notificacao":
        sucesso, res = cancelar_notificacao(args.get("id_ou_contexto", ""))
        return f"🗑️ Lembrete cancelado!" if sucesso else f"❌ {res}"
    return f"❌ Função desconhecida."

def _normalizar_historico(historico):
    """
    Garante que TODA mensagem tenha content como lista de blocos.
    Strings legadas viram [{"type": "text", "text": str}].
    Roda só uma vez no começo de cada turno; barato e idempotente.
    """
    out = []
    for msg in historico:
        c = msg.get("content")
        if isinstance(c, str):
            out.append({"role": msg["role"], "content": [{"type": "text", "text": c}]})
        elif isinstance(c, list):
            out.append({"role": msg["role"], "content": list(c)})
        # ignora qualquer entrada malformada
    return out


def _truncar_em_boundary(historico, max_turnos):
    """
    Mantém últimos `max_turnos` turnos completos. Turno = user-text → ... → assistant-text.
    Nunca corta no meio de um par tool_use/tool_result. Garante 1ª msg = user-text.
    """
    if not historico:
        return historico
    # Marca índices onde começa um turno: user com bloco type=text (não tool_result).
    inicios = []
    for i, m in enumerate(historico):
        if m["role"] != "user":
            continue
        blocos = m.get("content", [])
        if any(isinstance(b, dict) and b.get("type") == "text" for b in blocos):
            inicios.append(i)
    if len(inicios) <= max_turnos:
        return historico
    corte = inicios[-max_turnos]
    return historico[corte:]


def _validar_pareamento(historico):
    """
    Retorna True se todo tool_use tem tool_result subsequente e vice-versa.
    Usa só pra debug/asserção, nunca pra mascarar bug.
    """
    pendentes = set()
    for m in historico:
        for b in m.get("content", []):
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "tool_use":
                pendentes.add(b.get("id"))
            elif t == "tool_result":
                pendentes.discard(b.get("tool_use_id"))
    return not pendentes


def _chamar_claude(historico_blocos):
    """Chama API. Retorna dict da resposta ou levanta exceção com body detalhado."""
    headers = {
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        "x-api-key": CHAVE_ANTHROPIC,
    }
    system_blocks = [{
        "type": "text",
        "text": _montar_instrucao_mestre(),
        "cache_control": {"type": "ephemeral"},
    }]
    payload = {
        "model": MODELO_CLAUDE,
        "max_tokens": OPCOES_CLAUDE["max_tokens"],
        "temperature": OPCOES_CLAUDE["temperature"],
        "system": system_blocks,
        "messages": historico_blocos,
        "tools": _construir_tools_schema(),
    }
    r = requests.post(URL_API_CLAUDE, headers=headers, json=payload, timeout=30)
    if r.status_code >= 400:
        raise Exception(f"HTTP {r.status_code} | {r.text[:800]}")
    return r.json()


def processar_mensagem(mensagem_usuario_crua, historico, auto_confirmar_gravacao=False, chat_id=None):
    """
    Refatorado (Abril 2026):
    - Histórico SEMPRE em blocos (sem string solta).
    - Turno é atômico: user-text → [tool_use → tool_result]* → assistant-text sintético.
    - Truncamento por boundary de turno (nunca corta par tool_use/tool_result).
    - Em erro, faz rollback do user appendado pra histórico ficar consistente.
    - Loop interno com cap de 4 rodadas (Claude pode encadear tools).
    """
    MAX_RODADAS_TOOL = 4
    MAX_TURNOS_HISTORICO = 8
    API_MAX_TENTATIVAS = 3
    API_BACKOFF = 2

    # 1) Normaliza qualquer estado legado
    historico = _normalizar_historico(historico)

    # 2) Append do user (formato canônico: lista de blocos)
    msg_enriquecida = _enriquecer_mensagem_com_data(mensagem_usuario_crua)
    historico.append({
        "role": "user",
        "content": [{"type": "text", "text": msg_enriquecida}],
    })

    # 3) Trunca por turno (preserva pares tool_use/tool_result)
    historico = _truncar_em_boundary(historico, MAX_TURNOS_HISTORICO)

    if DEBUG_EXTRACAO and not _validar_pareamento(historico):
        print("[DEBUG] Histórico desbalanceado entrando no turno.")

    # Snapshot pra rollback em caso de erro
    historico_pre_turno = [dict(m) for m in historico[:-1]]

    respostas_humanas = []

    try:
        for rodada in range(MAX_RODADAS_TOOL):
            # ---- Chamada API com retry ----
            ultimo_erro = None
            resposta = None
            for tentativa in range(1, API_MAX_TENTATIVAS + 1):
                try:
                    resposta = _chamar_claude(historico)
                    ultimo_erro = None
                    break
                except Exception as e:
                    ultimo_erro = e
                    if tentativa < API_MAX_TENTATIVAS:
                        _time.sleep(API_BACKOFF)
            if ultimo_erro:
                raise ultimo_erro

            blocos_resposta = resposta.get("content", [])
            historico.append({"role": "assistant", "content": blocos_resposta})

            tool_calls = [b for b in blocos_resposta if b.get("type") == "tool_use"]

            # ---- Resposta de texto (turno fecha) ----
            if not tool_calls:
                textos = [b.get("text", "") for b in blocos_resposta if b.get("type") == "text"]
                final = " ".join(textos).strip() or "Não entendi."
                respostas_humanas.append(final)
                return "\n\n".join(respostas_humanas), historico

            # ---- Executa tools ----
            tool_results = []
            for tc in tool_calls:
                try:
                    resultado = _executar_tool_call(
                        tc["name"], tc.get("input", {}),
                        mensagem_usuario_crua, msg_enriquecida,
                        auto_confirmar_gravacao, chat_id,
                    )
                except Exception as ex:
                    resultado = f"❌ Erro executando {tc['name']}: {ex}"
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": resultado,
                })
                respostas_humanas.append(resultado)

            historico.append({"role": "user", "content": tool_results})

            # Atalho: tool já produziu HTML formatado pro usuário.
            # Em vez de gastar 2ª chamada API, sintetizamos assistant-text
            # com o resultado e fechamos o turno limpo.
            texto_final = "\n\n".join(respostas_humanas)
            historico.append({
                "role": "assistant",
                "content": [{"type": "text", "text": texto_final}],
            })
            return texto_final, historico

        # Cap de rodadas atingido
        raise Exception(f"Loop tool excedeu {MAX_RODADAS_TOOL} rodadas sem fechar turno.")

    except Exception as e:
        # Rollback: restaura histórico pré-turno pra não envenenar próximas chamadas
        return f"❌ Erro na API Claude: {e}", historico_pre_turno

def rodar_agente(chave_gemini=None):
    print("✅ Motor Claude Haiku 4.5 ativo com controle de custos.")
    historico = criar_historico_novo()
    while True:
        msg = input("\n🙋 Você: ").strip()
        if not msg or msg.lower() in COMANDOS_DE_SAIDA: break
        res, historico = processar_mensagem(msg, historico)
        print(f"\n🤖 Trembinho: {res}")