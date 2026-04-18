"""
TREMBINHO - Integração Notion (API 2025-09-03)
===============================================
Responsável por criar, LISTAR e EDITAR páginas na database "trembobase".
- Consulta via data_sources.query (Padrão 2026).
- Filtros dinâmicos por Tipo, Status e RANGE DE DATA (Início/Fim).
- Double-check [Y/n] para gravação (com bypass para canais assíncronos como Telegram).
- Fix de fuso horário via campo time_zone.

SPRINT 4 - BIDIRECIONAL:
- Adicionado parâmetro `auto_confirmar` em criar_pagina_no_notion().
- Default False preserva comportamento do terminal (pede [Y/n]).
- Telegram Listener passará True para pular o prompt (não trava o bot).

SPRINT 4 / PASSO 5.6 - NOVO CONTRATO DE LISTAGEM:
- listar_itens_no_notion() agora devolve ESTRUTURA em vez de string crua:
    • Sucesso: lista de dicts com chaves {page_id, nome, tipo, status, data, descricao}
    • Erro:    {"erro": "mensagem descritiva"}
    • Vazio:   lista vazia []
- A formatação (cards, emojis, cabeçalho) é responsabilidade da camada acima
  (agente.py), mantendo esta camada focada em I/O puro.
- Retrocompatibilidade: listar_itens_formatado_legado() devolve a string crua
  antiga, usada por verificar_pendencias.py até a migração do Passo 5.6.C.

EDIÇÃO (Sprint 5):
- buscar_paginas_por_nome(): busca case-insensitive por substring do nome.
- atualizar_pagina_no_notion(): PATCH parcial em qualquer campo.
"""

import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from notion_client import Client

# -----------------------------------------------------------------------------
# Carregamento de credenciais
# -----------------------------------------------------------------------------
load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# Cliente Notion fixado na versão da API exigida pelo projeto (2025-09-03)
notion = Client(auth=NOTION_API_KEY, notion_version="2025-09-03")

# Fuso do projeto — Brasília
FUSO_HORARIO_IANA = "America/Sao_Paulo"


# -----------------------------------------------------------------------------
# Helpers de descoberta e sanitização
# -----------------------------------------------------------------------------
def obter_data_source_id():
    """Busca o data_source_id a partir do database_id configurado."""
    if not NOTION_DATABASE_ID:
        print("[ERRO] NOTION_DATABASE_ID não encontrado no .env")
        return None
    try:
        banco = notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
        return banco["data_sources"][0]["id"]
    except Exception as e:
        print(f"[ERRO] Falha ao buscar data_source_id: {e}")
        return None


def _limpar_offset_se_houver(data_str):
    """Remove offset (+03:00) para compatibilidade com time_zone."""
    if data_str.endswith("Z"):
        data_str = data_str[:-1]
    if "T" in data_str:
        parte_data, parte_hora = data_str.split("T", 1)
        for sep in ("+", "-"):
            if sep in parte_hora:
                parte_hora = parte_hora.split(sep)[0]
                break
        data_str = f"{parte_data}T{parte_hora}"
    return data_str


def _extrair_rich_text(rich_text_array):
    """Concatena todos os segmentos de um campo rich_text do Notion."""
    if not rich_text_array:
        return ""
    return "".join(bloco.get("plain_text", "") for bloco in rich_text_array)


# -----------------------------------------------------------------------------
# FUNÇÃO DE CONSULTA — NOVO CONTRATO (Passo 5.6)
# -----------------------------------------------------------------------------
def listar_itens_no_notion(tipo=None, status=None, data_inicio=None, data_fim=None):
    """
    Consulta o data_source do Notion aplicando filtros opcionais.
    Suporta busca por período (data_inicio até data_fim) ou dia exato.

    Returns:
        list[dict]: lista de itens no formato:
            {
                "nome": str,
                "tipo": str,      # "Lead" | "Tarefa" | "Nota" | "Ideia" | "?"
                "status": str,    # "Aberto" | "Em andamento" | "Concluído" | "?"
                "data": str,      # ISO 8601 ou "Sem data"
                "descricao": str  # pode ser string vazia
            }
        dict: {"erro": "mensagem"} em caso de falha de acesso/consulta.
        list vazia: [] quando não há itens (ausência de erro).
    """
    ds_id = obter_data_source_id()
    if not ds_id:
        return {"erro": "Não foi possível acessar a base de dados do Notion."}

    filtros_lista = []

    if tipo:
        filtros_lista.append({"property": "Tipo", "select": {"equals": tipo}})
    if status:
        filtros_lista.append({"property": "Status", "select": {"equals": status}})

    # Lógica de Filtro de Datas (O pulo do gato)
    if data_inicio or data_fim:
        d_inicio = data_inicio.split("T")[0] if data_inicio else None
        d_fim = data_fim.split("T")[0] if data_fim else None

        if d_inicio and d_fim and d_inicio == d_fim:
            # É o mesmo dia exato (ex: "tarefas de hoje")
            filtros_lista.append({"property": "Data", "date": {"equals": d_inicio}})
        else:
            # É um período (ex: "tarefas do mês que vem")
            if d_inicio:
                filtros_lista.append({"property": "Data", "date": {"on_or_after": d_inicio}})
            if d_fim:
                filtros_lista.append({"property": "Data", "date": {"on_or_before": d_fim}})

    query_params = {"data_source_id": ds_id}
    if filtros_lista:
        query_params["filter"] = {"and": filtros_lista} if len(filtros_lista) > 1 else filtros_lista[0]

    try:
        resultado = notion.data_sources.query(**query_params)
        paginas = resultado.get("results", [])

        itens = []
        for p in paginas:
            props = p.get("properties", {})

            # Nome (title)
            title_array = props.get("Nome", {}).get("title", [])
            nome = _extrair_rich_text(title_array) or "Sem título"

            # Tipo e Status (select)
            t = (props.get("Tipo", {}).get("select") or {}).get("name", "?")
            s = (props.get("Status", {}).get("select") or {}).get("name", "?")

            # Data
            d = (props.get("Data", {}).get("date") or {}).get("start", "Sem data")

            # Descrição (rich_text) - pode não existir
            desc_array = props.get("Descrição", {}).get("rich_text", [])
            descricao = _extrair_rich_text(desc_array)

            itens.append({
                "page_id": p.get("id", ""),
                "nome": nome,
                "tipo": t,
                "status": s,
                "data": d,
                "descricao": descricao,
            })

        return itens

    except Exception as e:
        return {"erro": f"Erro ao consultar o Notion: {str(e)}"}


# -----------------------------------------------------------------------------
# RETROCOMPATIBILIDADE - string crua antiga (deprecar no Passo 5.6.C)
# -----------------------------------------------------------------------------
def listar_itens_formatado_legado(tipo=None, status=None, data_inicio=None, data_fim=None):
    """
    Wrapper de compatibilidade: devolve a string crua no formato pré-5.6.
    
    Usado por verificar_pendencias.py enquanto não migra pro novo contrato.
    Será removido no Passo 5.6.C.
    
    DEPRECATED: use listar_itens_no_notion() e formate na camada consumidora.
    """
    resultado = listar_itens_no_notion(tipo, status, data_inicio, data_fim)

    # Erro
    if isinstance(resultado, dict) and "erro" in resultado:
        return f"Erro: {resultado['erro']}"

    # Vazio
    if not resultado:
        return "Nenhum item encontrado com esses filtros no período solicitado."

    # Lista de dicts -> string crua antiga
    linhas = [
        f"- [{item['tipo']}] {item['nome']} | Status: {item['status']} | Data: {item['data']}"
        for item in resultado
    ]
    return "\n".join(linhas)


# -----------------------------------------------------------------------------
# FUNÇÃO DE GRAVAÇÃO (com bypass de confirmação para canais assíncronos)
# -----------------------------------------------------------------------------
def criar_pagina_no_notion(nome, tipo, status, data, descricao, auto_confirmar=False):
    """
    Cria uma nova linha no database.
    
    Args:
        nome, tipo, status, data, descricao: campos da página.
        auto_confirmar: 
            - False (default): modo terminal. Pede [Y/n] antes de gravar.
            - True: modo assíncrono (Telegram). Pula o prompt e grava direto.
              O double-check deve ser feito PELO CHAMADOR antes de acionar essa função.
    
    Returns:
        True se gravou, False se cancelou ou deu erro.
    """
    data_str = str(data or "").strip()
    tem_hora = "T" in data_str

    if not tem_hora:
        propriedade_data = {"date": {"start": data_str}}
    else:
        data_limpa = _limpar_offset_se_houver(data_str)
        propriedade_data = {
            "date": {
                "start": data_limpa,
                "time_zone": FUSO_HORARIO_IANA,
            }
        }

    # -------------------------------------------------------------------------
    # Double-check [Y/n] - só roda no modo terminal (bloqueante).
    # No modo assíncrono (Telegram), o chamador já validou a intenção.
    # -------------------------------------------------------------------------
    if not auto_confirmar:
        print(f"\n🤖 Trembinho: Vou criar {tipo} '{nome}' ({status}) para {data_str}. Manda ver? [Y/n]: ", end="")
        confirmacao = input().strip().lower()

        if confirmacao not in {"y", "yes", "s", "sim", ""}:
            print("❌ Cancelado.")
            return False
    else:
        # Log silencioso para rastreabilidade (útil se rodar terminal + listener simultâneos)
        print(f"[NOTION/AUTO] Gravando: {tipo} '{nome}' ({status}) para {data_str}")

    ds_id = obter_data_source_id()
    try:
        notion.pages.create(
            parent={"data_source_id": ds_id},
            properties={
                "Nome": {"title": [{"text": {"content": nome}}]},
                "Tipo": {"select": {"name": tipo}},
                "Status": {"select": {"name": status}},
                "Data": propriedade_data,
                "Descrição": {"rich_text": [{"text": {"content": descricao}}]},
            },
        )
        return True
    except Exception as e:
        print(f"[ERRO] {e}")
        return False


# -----------------------------------------------------------------------------
# BUSCA POR NOME (para edição)
# -----------------------------------------------------------------------------
def buscar_paginas_por_nome(nome_busca):
    """
    Retorna todas as entradas cujo campo Nome contenha nome_busca (case-insensitive).

    Returns:
        list[dict]: itens com {page_id, nome, tipo, status, data, descricao}
        dict: {"erro": "mensagem"} em caso de falha.
    """
    todos = listar_itens_no_notion()
    if isinstance(todos, dict) and "erro" in todos:
        return todos
    termo = nome_busca.strip().lower()
    return [item for item in todos if termo in item.get("nome", "").lower()]


# -----------------------------------------------------------------------------
# ATUALIZAÇÃO DE PÁGINA (PATCH parcial)
# -----------------------------------------------------------------------------
def atualizar_pagina_no_notion(page_id, campos):
    """
    Atualiza apenas os campos fornecidos em uma página existente.

    Args:
        page_id (str): ID da página no Notion.
        campos (dict): chaves em {nome, tipo, status, data, descricao} — apenas
                       os que devem ser alterados. Campos ausentes não são tocados.

    Returns:
        True se atualizou, False em caso de erro.
    """
    properties = {}

    if campos.get("nome"):
        properties["Nome"] = {"title": [{"text": {"content": campos["nome"]}}]}

    if campos.get("tipo"):
        properties["Tipo"] = {"select": {"name": campos["tipo"]}}

    if campos.get("status"):
        properties["Status"] = {"select": {"name": campos["status"]}}

    if campos.get("data"):
        data_str = str(campos["data"]).strip()
        tem_hora = "T" in data_str
        if not tem_hora:
            properties["Data"] = {"date": {"start": data_str}}
        else:
            data_limpa = _limpar_offset_se_houver(data_str)
            properties["Data"] = {"date": {"start": data_limpa, "time_zone": FUSO_HORARIO_IANA}}

    if campos.get("descricao") is not None and campos["descricao"] != "":
        properties["Descrição"] = {"rich_text": [{"text": {"content": campos["descricao"]}}]}

    if not properties:
        print("[NOTION/EDIT] Nenhum campo para atualizar.")
        return False

    print(f"[NOTION/EDIT] Atualizando page_id={page_id}: {list(properties.keys())}")
    try:
        notion.pages.update(page_id=page_id, properties=properties)
        return True
    except Exception as e:
        print(f"[ERRO] Falha ao atualizar página: {e}")
        return False


# -----------------------------------------------------------------------------
# EXCLUSÃO DE PÁGINA (arquivamento — reversível pelo site do Notion)
# -----------------------------------------------------------------------------
def excluir_pagina_no_notion(page_id):
    """
    Arquiva uma página no Notion (equivalente a "deletar" pela API).
    A página some do database mas pode ser restaurada pelo site do Notion.

    Returns:
        True se arquivou, False em caso de erro.
    """
    print(f"[NOTION/DEL] Arquivando page_id={page_id}")
    try:
        notion.pages.update(page_id=page_id, archived=True)
        return True
    except Exception as e:
        print(f"[ERRO] Falha ao arquivar página: {e}")
        return False