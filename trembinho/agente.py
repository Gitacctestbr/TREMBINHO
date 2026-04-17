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

# temperature=0.3 -> deixa o Qwen obediente ao function calling, menos criativo.
OPCOES_OLLAMA = {
    "temperature": 0.3,
    "num_ctx": 8192,
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
# Instrução mestre (system prompt) - centralizada para reuso
# -----------------------------------------------------------------------------
def _montar_instrucao_mestre():
    """Monta o system prompt com contexto temporal atualizado. 
    Exposta para que o Telegram Listener também possa criar históricos novos."""
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
    """Retorna um histórico limpo com o system prompt injetado.
    Usado tanto pelo terminal quanto pelo listener do Telegram."""
    return [{"role": "system", "content": _montar_instrucao_mestre()}]

# -----------------------------------------------------------------------------
# MOTOR PURO - processa uma mensagem e retorna a resposta
# -----------------------------------------------------------------------------
def processar_mensagem(mensagem_usuario_crua, historico):
    """
    Motor de raciocínio do Trembinho, desacoplado de qualquer interface.
    
    Args:
        mensagem_usuario_crua: texto bruto que o usuário digitou.
        historico: lista de mensagens (role/content) mantida entre turnos.
    
    Returns:
        tupla (resposta_texto: str, historico_atualizado: list).
    
    Side effects controlados:
        - Pode chamar criar_pagina_no_notion() (que ainda pede [Y/n] via input).
        - Pode chamar listar_itens_no_notion() (consulta pura).
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
            # Fallback Regex para as duas funções
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

        if args is not None and nome_funcao:

            # ROTA 1: LISTAR (COM RANGE DE DATAS)
            if nome_funcao == "ferramenta_listar_notion":
                t_bruto = args.get("tipo")
                s_bruto = args.get("status")
                d_ini_bruto = args.get("data_inicio")
                d_fim_bruto = args.get("data_fim")
                data_legado = args.get("data")  # Caso a LLM alucine o formato antigo

                # Limpeza de filtros vazios
                t_filtro = t_bruto.capitalize() if t_bruto and str(t_bruto).strip() else None
                s_filtro = s_bruto.capitalize() if s_bruto and str(s_bruto).strip() else None
                if s_filtro == "Em Andamento":
                    s_filtro = "Em andamento"

                # Formata as datas
                d_ini_filtro = formatar_data_iso(d_ini_bruto) if d_ini_bruto and str(d_ini_bruto).strip() else None
                d_fim_filtro = formatar_data_iso(d_fim_bruto) if d_fim_bruto and str(d_fim_bruto).strip() else None

                # Fallback de segurança: se ele mandou só 'data', converte para inicio/fim no mesmo dia
                if data_legado and not d_ini_filtro and not d_fim_filtro:
                    d_legado_formatado = formatar_data_iso(data_legado)
                    d_ini_filtro = d_legado_formatado
                    d_fim_filtro = d_legado_formatado

                resultado = listar_itens_no_notion(t_filtro, s_filtro, d_ini_filtro, d_fim_filtro)
                return (f"Tá na mão, chefe:\n\n{resultado}", historico)

            # ROTA 2: SALVAR
            elif nome_funcao == "ferramenta_salvar_notion":
                nome_limpo = args.get("nome") or args.get("nome_do_lead") or "Nova Entrada"

                tipos_validos = {"Lead", "Tarefa", "Nota", "Ideia"}
                tipo_bruto = str(args.get("tipo", "")).strip().capitalize()
                tipo_limpo = tipo_bruto if tipo_bruto in tipos_validos else ("Lead" if "lead" in str(args).lower() else "Tarefa")

                status_validos = {"Aberto", "Em andamento", "Concluído"}
                status_bruto = str(args.get("status", "")).strip().capitalize()
                if status_bruto == "Em Andamento":
                    status_bruto = "Em andamento"
                status_limpo = status_bruto if status_bruto in status_validos else "Aberto"

                data_limpa = formatar_data_iso(args.get("data", data_hoje), mensagem_original=mensagem_usuario_crua)
                desc_limpa = args.get("descricao") or f"Registrado via Trembinho em {data_hoje}"

                if criar_pagina_no_notion(nome_limpo, tipo_limpo, status_limpo, data_limpa, desc_limpa):
                    return ("Feito! Já organizei isso lá no seu banco de dados.", historico)
                else:
                    return ("Cara, eu tentei salvar, mas a conexão falhou ou você cancelou.", historico)

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

        # Indicadores visuais simples antes da chamada (preservando UX do terminal)
        print("\n⏳ [SISTEMA] Processando...")

        resposta, historico = processar_mensagem(mensagem_usuario_crua, historico)

        print(f"\n🤖 Trembinho: {resposta}")