"""
TREMBINHO - Interpretação de Datas em Linguagem Natural (Sprint 1)
===================================================================
Tira a responsabilidade do Qwen 14B de calcular datas — modelo local
é notoriamente ruim em aritmética de calendário. Aqui a gente resolve
tudo em Python puro, de forma determinística.

ESTRATÉGIA EM CASCATA (do mais rápido para o mais flexível):
  Camada 0: Palavras-chave triviais (hoje, amanhã, ontem, depois de amanhã)
  Camada 1: Regex brasileiro (datas no formato DD/MM, horas HH:MM)
  Camada 2: Dias da semana em português (mapa determinístico)
  Camada 3: Regex "daqui a X dias/semanas/meses"
  Camada 4: dateparser v1.4+ como fallback universal
  Camada 5: Combinação de data + hora quando ambos aparecem

SAÍDA: sempre uma string ISO 8601 compatível com o campo 'Data' do
Notion (que aceita tanto 'YYYY-MM-DD' quanto 'YYYY-MM-DDTHH:MM:00').
"""

import re
from datetime import datetime, timedelta
import dateparser


# -----------------------------------------------------------------------------
# Mapeamento de dias da semana em português
# -----------------------------------------------------------------------------
# Python: Monday=0, Tuesday=1, Wednesday=2, Thursday=3, Friday=4, Saturday=5, Sunday=6
DIAS_SEMANA = {
    "segunda": 0, "segunda-feira": 0, "seg": 0,
    "terca": 1, "terca-feira": 1, "ter": 1,
    "quarta": 2, "quarta-feira": 2, "qua": 2,
    "quinta": 3, "quinta-feira": 3, "qui": 3,
    "sexta": 4, "sexta-feira": 4, "sex": 4,
    "sabado": 5, "sab": 5,
    "domingo": 6, "dom": 6,
}

# Padrões regex reutilizáveis
PADRAO_DATA_BR = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")

# Hora: captura "14h", "14h30", "14:30", "às 14h", "às 14:30", "9h", etc.
# Os minutos podem estar depois de ':' OU depois de 'h' ("14h30")
PADRAO_HORA = re.compile(
    r"(?:às\s+|as\s+|@\s*)?"        # prefixo opcional
    r"(\d{1,2})"                    # hora
    r"(?::(\d{2})|h(\d{2})?)"       # :MM  OU  h  OU  hMM
    r"(?:\s*(?:hrs?|horas?))?",     # sufixo opcional
    re.IGNORECASE,
)

PADRAO_DIA_SEMANA = re.compile(
    r"\b(pr[oó]xim[ao]\s+|essa\s+|esta\s+)?"
    r"(segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo)"
    r"(?:-?feira)?"
    r"(\s+que\s+vem)?\b",
    re.IGNORECASE,
)

# "daqui a 3 dias", "daqui a 2 semanas", "daqui 1 mês"
PADRAO_DAQUI_A = re.compile(
    r"\bdaqui\s+(?:a\s+)?(\d+)\s+(dia|dias|semana|semanas|m[eê]s|m[eê]ses)\b",
    re.IGNORECASE,
)


# -----------------------------------------------------------------------------
# Camada 1: Regex de data brasileira (DD/MM ou DD/MM/YYYY)
# -----------------------------------------------------------------------------
def _extrair_data_br(texto):
    """Tenta capturar datas no formato DD/MM ou DD/MM/YYYY. Retorna datetime ou None."""
    match = PADRAO_DATA_BR.search(texto)
    if not match:
        return None
    try:
        dia = int(match.group(1))
        mes = int(match.group(2))
        ano_str = match.group(3)
        if ano_str:
            ano = int(ano_str)
            if ano < 100:  # "24" vira "2024"
                ano += 2000
        else:
            ano = datetime.now().year
        return datetime(ano, mes, dia)
    except (ValueError, TypeError):
        return None


# -----------------------------------------------------------------------------
# Camada 2: Dias da semana em português (determinístico)
# -----------------------------------------------------------------------------
def _extrair_dia_semana(texto, base=None):
    """
    Captura 'próxima terça', 'sexta que vem', 'terça-feira'. Retorna datetime ou None.
    Regra: SEMPRE retorna o próximo dia correspondente no futuro.
    """
    if base is None:
        base = datetime.now()

    match = PADRAO_DIA_SEMANA.search(texto.lower())
    if not match:
        return None

    # Normaliza: remove ç, á
    dia_nome = match.group(2).replace("ç", "c").replace("á", "a")
    dia_alvo = DIAS_SEMANA.get(dia_nome)
    if dia_alvo is None:
        return None

    dia_atual = base.weekday()
    delta = (dia_alvo - dia_atual) % 7
    if delta == 0:
        delta = 7  # "terça" numa terça = próxima terça, não hoje

    return (base + timedelta(days=delta)).replace(hour=0, minute=0, second=0, microsecond=0)


# -----------------------------------------------------------------------------
# Camada 3: "daqui a X dias/semanas/meses" (dateparser fraqueja aqui em PT)
# -----------------------------------------------------------------------------
def _extrair_daqui_a(texto):
    """Captura 'daqui a 3 dias', 'daqui 2 semanas'. Retorna datetime ou None."""
    match = PADRAO_DAQUI_A.search(texto.lower())
    if not match:
        return None
    try:
        qtd = int(match.group(1))
        unidade = match.group(2).lower()
        hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        if unidade.startswith("dia"):
            return hoje + timedelta(days=qtd)
        elif unidade.startswith("semana"):
            return hoje + timedelta(weeks=qtd)
        elif unidade.startswith("m"):  # mês/meses
            # Aproximação: 30 dias por mês (suficiente para lembretes)
            return hoje + timedelta(days=qtd * 30)
    except (ValueError, TypeError):
        pass
    return None


# -----------------------------------------------------------------------------
# Extração de hora (independente da data)
# -----------------------------------------------------------------------------
def _extrair_hora(texto):
    """
    Captura '14h', 'às 14h30', '9:00', '14:30'. Retorna tupla (hora, minuto) ou None.
    Suporta três formatos de minutos:
      - HH:MM  (ex: "14:30", "às 16:30")
      - HHhMM  (ex: "9h30")
      - HHh    (ex: "14h", sem minutos)
    """
    match = PADRAO_HORA.search(texto)
    if not match:
        return None
    try:
        hora = int(match.group(1))
        # Minutos podem vir do grupo 2 (formato :MM) ou do grupo 3 (formato hMM)
        min_str = match.group(2) or match.group(3)
        minuto = int(min_str) if min_str else 0
        if 0 <= hora <= 23 and 0 <= minuto <= 59:
            return (hora, minuto)
    except (ValueError, TypeError):
        pass
    return None


# -----------------------------------------------------------------------------
# Camada 4: dateparser como fallback universal
# -----------------------------------------------------------------------------
def _fallback_dateparser(texto):
    """Último recurso: dateparser em português com preferência pelo futuro."""
    try:
        resultado = dateparser.parse(
            texto,
            languages=["pt"],
            settings={
                "PREFER_DATES_FROM": "future",
                "DATE_ORDER": "DMY",
                "RETURN_AS_TIMEZONE_AWARE": False,
            },
        )
        return resultado
    except Exception:
        return None


# -----------------------------------------------------------------------------
# Função principal (o que o agente.py vai chamar)
# -----------------------------------------------------------------------------
def interpretar_data(texto, incluir_hora=True):
    """
    Interpreta uma frase em linguagem natural e retorna uma data ISO 8601.

    Args:
        texto: frase ou pedaço de frase contendo referência temporal.
        incluir_hora: se True e houver hora na frase, retorna formato
                      'YYYY-MM-DDTHH:MM:00'. Senão, só 'YYYY-MM-DD'.

    Returns:
        String ISO ('2026-04-21' ou '2026-04-21T14:00:00') ou None se
        não conseguir interpretar.
    """
    if not texto or not isinstance(texto, str):
        return None

    texto_limpo = texto.strip().lower()
    hoje = datetime.now()

    # -------------------------------------------------------------------------
    # Camada 0: Palavras-chave triviais
    # ATENÇÃO: ORDEM IMPORTA. "depois de amanhã" deve ser checado ANTES
    # de "amanhã" sozinho, senão o regex menor captura primeiro.
    # -------------------------------------------------------------------------
    if re.search(r"\bdepois\s+de\s+amanh[ãa]\b", texto_limpo):
        data_base = (hoje + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif re.search(r"\bhoje\b", texto_limpo):
        data_base = hoje.replace(hour=0, minute=0, second=0, microsecond=0)
    elif re.search(r"\bamanh[ãa]\b", texto_limpo):
        data_base = (hoje + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif re.search(r"\bontem\b", texto_limpo):
        data_base = (hoje - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        # Camada 1: DD/MM
        data_base = _extrair_data_br(texto_limpo)
        # Camada 2: dia da semana
        if data_base is None:
            data_base = _extrair_dia_semana(texto_limpo)
        # Camada 3: "daqui a X dias/semanas"
        if data_base is None:
            data_base = _extrair_daqui_a(texto_limpo)
        # Camada 4: fallback dateparser (catch-all)
        if data_base is None:
            data_base = _fallback_dateparser(texto_limpo)

    if data_base is None:
        return None

    # Camada 5: se pedido e houver hora, combina
    if incluir_hora:
        hora_extraida = _extrair_hora(texto_limpo)
        if hora_extraida:
            hora, minuto = hora_extraida
            data_base = data_base.replace(hour=hora, minute=minuto, second=0, microsecond=0)
            return data_base.strftime("%Y-%m-%dT%H:%M:00")

    # Sem hora → só data
    return data_base.strftime("%Y-%m-%d")


# -----------------------------------------------------------------------------
# Bateria de teste — rode com: python -m trembinho.datas
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print("🚂 TREMBINHO - Teste do módulo datas.py (v2 corrigido)")
    print("=" * 60)
    print(f"Hoje é: {datetime.now().strftime('%Y-%m-%d (%A)')}")
    print("=" * 60)

    casos = [
        ("hoje", "2026-04-16"),
        ("amanhã", "2026-04-17"),
        ("ontem", "2026-04-15"),
        ("depois de amanhã", "2026-04-18"),   # era bug, agora deve dar 18
        ("próxima terça", "2026-04-21"),
        ("terça que vem", "2026-04-21"),
        ("sexta", "2026-04-17"),
        ("sexta-feira", "2026-04-17"),
        ("16/04", "2026-04-16"),
        ("16/04/2026", "2026-04-16"),
        ("21/04", "2026-04-21"),
        ("amanhã às 14h", "2026-04-17T14:00:00"),
        ("próxima terça às 9h30", "2026-04-21T09:30:00"),
        ("sexta às 16:30", "2026-04-17T16:30:00"),   # era bug, agora deve capturar :30
        ("daqui a 3 dias", "2026-04-19"),             # era None, agora deve dar 19
        ("daqui a 2 semanas", "2026-04-30"),
        ("em 2 semanas", "2026-04-30"),
        ("frase sem data nenhuma", None),
    ]

    acertos = 0
    total = len(casos)

    for frase, esperado in casos:
        resultado = interpretar_data(frase)
        ok = resultado == esperado
        if ok:
            acertos += 1
        marca = "✅" if ok else "❌"
        esperado_str = f"(esperado: {esperado})" if not ok else ""
        print(f"{marca} '{frase}'".ljust(45) + f"→ {resultado} {esperado_str}")

    print("=" * 60)
    print(f"Resultado: {acertos}/{total} acertos ({100*acertos//total}%)")