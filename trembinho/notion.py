"""
TREMBINHO - Integração Notion (API 2025-09-03)
===============================================
Responsável por criar e LISTAR páginas na database "trembobase".
- Consulta via data_sources.query (Padrão 2026).
- Filtros dinâmicos por Tipo, Status e RANGE DE DATA (Início/Fim).
- Double-check [Y/n] para gravação.
- Fix de fuso horário via campo time_zone.
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


# -----------------------------------------------------------------------------
# FUNÇÃO DE CONSULTA (ATUALIZADA SPRINT 2.5 - RANGE DE DATAS)
# -----------------------------------------------------------------------------
def listar_itens_no_notion(tipo=None, status=None, data_inicio=None, data_fim=None):
    """
    Consulta o data_source do Notion aplicando filtros opcionais.
    Suporta busca por período (data_inicio até data_fim) ou dia exato.
    """
    ds_id = obter_data_source_id()
    if not ds_id:
        return "Erro: Não foi possível acessar a base de dados do Notion."

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

        if not paginas:
            return "Nenhum item encontrado com esses filtros no período solicitado."

        linhas = []
        for p in paginas:
            props = p.get("properties", {})
            nome = props.get("Nome", {}).get("title", [{}])[0].get("plain_text", "Sem título")
            t = props.get("Tipo", {}).get("select", {}).get("name", "?")
            s = props.get("Status", {}).get("select", {}).get("name", "?")
            d = props.get("Data", {}).get("date", {}).get("start", "Sem data")
            
            linhas.append(f"- [{t}] {nome} | Status: {s} | Data: {d}")

        return "\n".join(linhas)

    except Exception as e:
        return f"Erro ao consultar o Notion: {str(e)}"


# -----------------------------------------------------------------------------
# FUNÇÃO DE GRAVAÇÃO (EXISTENTE)
# -----------------------------------------------------------------------------
def criar_pagina_no_notion(nome, tipo, status, data, descricao):
    """Cria uma nova linha no database com double-check [Y/n]."""
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

    print(f"\n🤖 Trembinho: Vou criar {tipo} '{nome}' ({status}) para {data_str}. Manda ver? [Y/n]: ", end="")
    confirmacao = input().strip().lower()

    if confirmacao not in {"y", "yes", "s", "sim", ""}:
        print("❌ Cancelado.")
        return False

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