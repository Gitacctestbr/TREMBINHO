"""
TREMBINHO - Agendador de Notificações
======================================
Gerencia notificações agendadas em linguagem natural.

Responsabilidades:
- Persistir fila em JSON (notificacoes_agendadas.json) para boot recovery.
- Thread daemon de verificação a cada 30s.
- Notificações ilimitadas simultâneas.
- Parsing determinístico de tempo em PT-BR (complementa datas.py).
- Envio via Telegram com parse_mode HTML.
- Edição e cancelamento de notificações por ID ou contexto.
"""

import html
import json
import os
import re
import threading
import uuid
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# Caminho absoluto baseado na localização deste módulo.
# Garante que o JSON é encontrado independente do CWD do processo chamador.
_DIR_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQUIVO_FILA = os.path.join(_DIR_BASE, "notificacoes_agendadas.json")
INTERVALO_VERIFICACAO = 30  # segundos
DEBUG_AGENDADOR = True  # log de cada interpretação de tempo

_lock = threading.Lock()
_thread_iniciada = False


# -----------------------------------------------------------------------------
# Parsing de tempo relativo (minutos/horas não cobertos pelo datas.py)
# -----------------------------------------------------------------------------

# Padrões: "em 5 minutos", "daqui 10 min", "em 2h", "em 1h30", "daqui a 2 horas"
_PADRAO_MINUTOS = re.compile(
    r"(?:em\s+|daqui\s+(?:a\s+)?)"
    r"(\d+)\s*"
    r"(?:minutos?|min\.?|mins?)",
    re.IGNORECASE,
)

_PADRAO_HORAS = re.compile(
    r"(?:em\s+|daqui\s+(?:a\s+)?)"
    r"(\d+)\s*h(?:oras?)?"
    r"(?:\s*(\d{1,2})\s*(?:min(?:utos?)?))?",
    re.IGNORECASE,
)

# "em 1h30min", "em 1h30"
_PADRAO_HORAS_MIN_COMPACTO = re.compile(
    r"(?:em\s+|daqui\s+(?:a\s+)?)"
    r"(\d+)\s*h\s*(\d{1,2})",
    re.IGNORECASE,
)

_PADRAO_SEGUNDOS = re.compile(
    r"(?:em\s+|daqui\s+(?:a\s+)?)"
    r"(\d+)\s*(?:segundos?|seg\.?)",
    re.IGNORECASE,
)

# Hora absoluta: "às 20:55", "20:55", "às 14h", "14h30", "9h", "08h00"
_PADRAO_HORA_ABSOLUTA = re.compile(
    r"(?:\b(?:às|as|@)\s*)?"          # prefixo opcional "às"
    r"\b(\d{1,2})"                    # hora (1-2 dígitos)
    r"(?::(\d{2})|h(\d{2})?)"         # :MM  OU  h  OU  hMM (obrigatório pra virar hora)
    r"(?:\s*(?:hrs?|horas?))?",       # sufixo opcional
    re.IGNORECASE,
)

# Modificadores de dia em português
_PADRAO_HOJE = re.compile(r"\bhoje\b", re.IGNORECASE)
_PADRAO_AMANHA = re.compile(r"\bamanh[ãa]\b", re.IGNORECASE)
_PADRAO_DEPOIS_AMANHA = re.compile(r"\bdepois\s+de\s+amanh[ãa]\b", re.IGNORECASE)
_PADRAO_DIA_SEMANA_SIMPLES = re.compile(
    r"\b(segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo)\b",
    re.IGNORECASE,
)


def _interpretar_hora_absoluta(texto, agora):
    """
    Parser determinístico de hora absoluta em PT-BR.

    Regra:
      - "amanhã às HH:MM"          -> amanhã HH:MM
      - "depois de amanhã às HH:MM"-> +2 dias HH:MM
      - "hoje às HH:MM"            -> hoje HH:MM (mesmo se já passou hoje)
      - dia da semana + hora       -> delega para datas.py (retorna None aqui)
      - só HH:MM, sem modificador  -> hoje HH:MM se ainda no futuro; senão amanhã

    Retorna datetime absoluto ou None se não achou hora absoluta.
    """
    m = _PADRAO_HORA_ABSOLUTA.search(texto)
    if not m:
        return None

    try:
        hora = int(m.group(1))
        min_str = m.group(2) or m.group(3)
        minuto = int(min_str) if min_str else 0
        if not (0 <= hora <= 23 and 0 <= minuto <= 59):
            return None
    except (ValueError, TypeError):
        return None

    # Dia da semana tem lógica própria — deixa o datas.py resolver
    if _PADRAO_DIA_SEMANA_SIMPLES.search(texto):
        return None

    if _PADRAO_DEPOIS_AMANHA.search(texto):
        base = agora + timedelta(days=2)
        explicito = True
    elif _PADRAO_AMANHA.search(texto):
        base = agora + timedelta(days=1)
        explicito = True
    elif _PADRAO_HOJE.search(texto):
        base = agora
        explicito = True
    else:
        base = agora
        explicito = False

    alvo = base.replace(hour=hora, minute=minuto, second=0, microsecond=0)

    # Sem "hoje"/"amanhã" explícito e hora já passou hoje → empurra pra amanhã
    if not explicito and alvo <= agora:
        alvo += timedelta(days=1)

    return alvo


def interpretar_tempo_relativo(texto):
    """
    Converte expressão de tempo relativo em datetime absoluto.

    Aceita: "em 5 minutos", "daqui 2 horas", "em 1h30", "daqui a 10min",
            "em 30 segundos", "em 1h30min", "às 14h30", "às 20:55 de hoje",
            "amanhã às 9h", "hoje às 23:59".

    Returns:
        datetime absoluto ou None se não conseguiu interpretar.
    """
    agora = datetime.now()
    resultado = _interpretar_com_log(texto, agora)
    if DEBUG_AGENDADOR:
        marca = resultado.strftime("%Y-%m-%d %H:%M:%S") if resultado else "None"
        print(f"[AGENDADOR DEBUG] tempo={texto!r} -> {marca} (agora={agora.strftime('%H:%M:%S')})")
    return resultado


def _interpretar_com_log(texto, agora):
    # Horas + minutos compacto: "em 1h30"
    m = _PADRAO_HORAS_MIN_COMPACTO.search(texto)
    if m:
        horas = int(m.group(1))
        mins = int(m.group(2))
        return agora + timedelta(hours=horas, minutes=mins)

    # Só horas: "em 2 horas" ou "em 2h30"
    m = _PADRAO_HORAS.search(texto)
    if m:
        horas = int(m.group(1))
        mins = int(m.group(2)) if m.group(2) else 0
        return agora + timedelta(hours=horas, minutes=mins)

    # Só minutos: "em 5 minutos"
    m = _PADRAO_MINUTOS.search(texto)
    if m:
        return agora + timedelta(minutes=int(m.group(1)))

    # Segundos (testes e demos)
    m = _PADRAO_SEGUNDOS.search(texto)
    if m:
        return agora + timedelta(seconds=int(m.group(1)))

    # Hora absoluta ("às 20:55", "hoje às 9h", "amanhã 14:30") — determinístico
    # IMPORTANTE: deve vir ANTES do dateparser — que tem bug PREFER_DATES_FROM=future
    # empurrando hora absoluta pro dia seguinte mesmo quando ainda é futura hoje.
    dt_abs = _interpretar_hora_absoluta(texto, agora)
    if dt_abs:
        return dt_abs

    # Fallback: datas.py (cobre dias da semana, DD/MM, "próxima terça" etc.)
    try:
        from trembinho.datas import interpretar_data
        resultado = interpretar_data(texto)
        if resultado:
            fmt = "%Y-%m-%dT%H:%M:00" if "T" in resultado else "%Y-%m-%d"
            dt = datetime.strptime(resultado, fmt)
            # Se datas.py retornou só data (meia-noite), assume 09:00 como padrão
            if dt.hour == 0 and dt.minute == 0 and "T" not in resultado:
                dt = dt.replace(hour=9)
            return dt
    except Exception:
        pass

    return None


def formatar_disparo_humano(dt):
    """
    Converte datetime de disparo em texto legível PT-BR.
    Ex: "em 5 min", "em 2h30", "hoje às 14:30", "amanhã às 09:00", "19/04 às 08:00"
    """
    agora = datetime.now()
    delta = dt - agora
    total_seg = int(delta.total_seconds())

    if total_seg < 0:
        return "agora"
    if total_seg < 60:
        return f"em {total_seg}s"
    if total_seg < 3600:
        mins = total_seg // 60
        return f"em {mins} min"
    if total_seg < 86400:
        horas = total_seg // 3600
        mins = (total_seg % 3600) // 60
        if mins:
            return f"em {horas}h{mins:02d}"
        return f"em {horas}h"

    # Mais de 24h — mostra dia e hora de forma legível
    hoje = agora.date()
    amanha = hoje + timedelta(days=1)
    hora_str = dt.strftime("%H:%M")

    if dt.date() == hoje:
        return f"hoje às {hora_str}"
    if dt.date() == amanha:
        return f"amanhã às {hora_str}"
    return f"{dt.strftime('%d/%m')} às {hora_str}"


# -----------------------------------------------------------------------------
# Persistência da fila
# -----------------------------------------------------------------------------

def _carregar_fila():
    if not os.path.exists(ARQUIVO_FILA):
        return []
    try:
        with open(ARQUIVO_FILA, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _salvar_fila(fila):
    with open(ARQUIVO_FILA, "w", encoding="utf-8") as f:
        json.dump(fila, f, ensure_ascii=False, indent=2)


# -----------------------------------------------------------------------------
# Envio para chat específico (não usa o chat_id global do .env)
# -----------------------------------------------------------------------------

def _enviar_para_chat(chat_id, mensagem):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("[AGENDADOR] TELEGRAM_BOT_TOKEN nao encontrado.")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": mensagem, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        # HTML rejeitado pelo Telegram — tenta plain text como fallback
        print(f"[AGENDADOR] Telegram rejeitou HTML (status {resp.status_code}): {resp.text[:200]}")
        texto_limpo = re.sub(r"<[^>]+>", "", mensagem)
        resp2 = requests.post(
            url,
            json={"chat_id": chat_id, "text": texto_limpo},
            timeout=10,
        )
        if resp2.status_code == 200:
            print("[AGENDADOR] Enviado em plain text apos fallback.")
            return True
        print(f"[AGENDADOR] Fallback plain text falhou: {resp2.text[:200]}")
        return False
    except Exception as e:
        print(f"[AGENDADOR] Excecao ao enviar: {e}")
        return False


# -----------------------------------------------------------------------------
# Geração de mensagem personalizada (template determinístico)
# -----------------------------------------------------------------------------

def _gerar_mensagem_notificacao(contexto_original, disparo_iso=None):
    """
    Gera o HTML do lembrete que será enviado quando a notificação disparar.
    Usa template determinístico — não depende do Qwen para garantir consistência.
    """
    ctx = html.escape(contexto_original)

    # Formata hora do disparo se disponível
    hora_str = ""
    if disparo_iso:
        try:
            dt = datetime.fromisoformat(disparo_iso)
            hora_str = f"\n🕐 <i>Agendado para: {dt.strftime('%d/%m às %H:%M')}</i>"
        except Exception:
            pass

    return (
        f"⏰ <b>Lembrete!</b>\n\n"
        f"📋 {ctx}"
        f"{hora_str}"
    )


# -----------------------------------------------------------------------------
# API pública do módulo
# -----------------------------------------------------------------------------

def agendar_notificacao(chat_id, contexto_original, disparo_em_iso):
    """
    Adiciona uma notificação à fila e persiste no JSON.
    Sem limite de notificações simultâneas.

    Args:
        chat_id: ID do chat Telegram (str ou int).
        contexto_original: texto exato que o usuário mandou.
        disparo_em_iso: datetime ISO ('2026-04-18T14:35:00') do disparo.

    Returns:
        (True, notif_dict)  — agendado com sucesso.
        (False, str_erro)   — falhou por erro interno.
    """
    with _lock:
        fila = _carregar_fila()

        mensagem_gerada = _gerar_mensagem_notificacao(contexto_original, disparo_em_iso)

        notif = {
            "id": str(uuid.uuid4())[:8],
            "chat_id": str(chat_id),
            "disparo_em": disparo_em_iso,
            "contexto_original": contexto_original,
            "mensagem_gerada": mensagem_gerada,
            "criado_em": datetime.now().strftime("%Y-%m-%dT%H:%M:00"),
            "status": "pendente",
        }
        fila.append(notif)
        _salvar_fila(fila)
        print(f"[AGENDADOR] Notificacao {notif['id']} agendada para {disparo_em_iso}.")
        return (True, notif)


def listar_pendentes():
    """Retorna lista das notificações com status 'pendente'."""
    fila = _carregar_fila()
    return [n for n in fila if n.get("status") == "pendente"]


def contar_pendentes():
    return len(listar_pendentes())


def cancelar_notificacao(notif_id):
    """
    Cancela uma notificação pendente pelo ID (8 chars).

    Returns:
        (True, notif_dict)  — cancelado com sucesso.
        (False, str_erro)   — não encontrou ou já disparou.
    """
    with _lock:
        fila = _carregar_fila()
        for notif in fila:
            if notif.get("id") == notif_id:
                if notif.get("status") != "pendente":
                    return (False, f"Notificacao {notif_id} ja esta com status '{notif['status']}'.")
                notif["status"] = "cancelado"
                notif["cancelado_em"] = datetime.now().strftime("%Y-%m-%dT%H:%M:00")
                _salvar_fila(fila)
                print(f"[AGENDADOR] Notificacao {notif_id} cancelada.")
                return (True, notif)
        return (False, f"Nao achei notificacao com ID '{notif_id}'.")


def editar_notificacao(notif_id, novo_tempo_iso=None, novo_contexto=None):
    """
    Edita tempo e/ou contexto de uma notificação pendente.

    Args:
        notif_id: ID de 8 chars da notificação.
        novo_tempo_iso: novo datetime ISO para disparo (opcional).
        novo_contexto: novo texto do lembrete (opcional).

    Returns:
        (True, notif_dict)  — editado.
        (False, str_erro)   — não encontrou ou já disparou.
    """
    with _lock:
        fila = _carregar_fila()
        for notif in fila:
            if notif.get("id") == notif_id:
                if notif.get("status") != "pendente":
                    return (False, f"Notificacao {notif_id} nao pode ser editada (status: {notif['status']}).")
                if novo_tempo_iso:
                    notif["disparo_em"] = novo_tempo_iso
                if novo_contexto:
                    notif["contexto_original"] = novo_contexto
                # Regenera mensagem com os dados novos
                notif["mensagem_gerada"] = _gerar_mensagem_notificacao(
                    notif["contexto_original"],
                    notif["disparo_em"],
                )
                _salvar_fila(fila)
                print(f"[AGENDADOR] Notificacao {notif_id} editada.")
                return (True, notif)
        return (False, f"Nao achei notificacao com ID '{notif_id}'.")


def buscar_notificacao_por_contexto(texto):
    """
    Busca notificações pendentes cujo contexto contenha o texto (case-insensitive).

    Returns:
        list[dict] — pode ser vazia.
    """
    texto_lower = texto.strip().lower()
    pendentes = listar_pendentes()
    return [
        n for n in pendentes
        if texto_lower in n.get("contexto_original", "").lower()
    ]


def formatar_lista_notificacoes(notificacoes=None):
    """
    Formata lista de notificações pendentes em HTML para o Telegram.

    Args:
        notificacoes: list[dict] ou None (busca pendentes automaticamente).

    Returns:
        String HTML pronta para envio.
    """
    if notificacoes is None:
        notificacoes = listar_pendentes()

    if not notificacoes:
        return (
            "⏰ <b>Notificações Agendadas</b>\n\n"
            "<i>Nenhuma notificação pendente no momento.</i>"
        )

    linhas = []
    for i, notif in enumerate(notificacoes, 1):
        ctx = html.escape(notif.get("contexto_original", "sem contexto"))
        notif_id = notif.get("id", "?")
        disparo_raw = notif.get("disparo_em", "")
        try:
            dt = datetime.fromisoformat(disparo_raw)
            disparo_str = formatar_disparo_humano(dt)
        except Exception:
            disparo_str = disparo_raw

        linhas.append(
            f"{i}. 📌 <b>{ctx}</b>\n"
            f"   🕐 {disparo_str} — <code>{notif_id}</code>"
        )

    total = len(notificacoes)
    rodape = f"\n<i>{total} notificao{'es' if total != 1 else 'ao'} na fila</i>"

    return (
        "⏰ <b>Notificações Agendadas</b>\n\n"
        + "\n\n".join(linhas)
        + "\n" + rodape
    )


# -----------------------------------------------------------------------------
# Loop de verificação
# -----------------------------------------------------------------------------

def _verificar_e_disparar():
    """Verifica notificações vencidas e dispara."""
    agora = datetime.now()

    with _lock:
        fila = _carregar_fila()
        alterou = False

        for notif in fila:
            if notif.get("status") != "pendente":
                continue
            try:
                disparo_dt = datetime.fromisoformat(notif["disparo_em"])
            except Exception:
                continue

            if agora >= disparo_dt:
                sucesso = _enviar_para_chat(notif["chat_id"], notif["mensagem_gerada"])
                notif["status"] = "disparado" if sucesso else "erro"
                notif["disparado_em"] = agora.strftime("%Y-%m-%dT%H:%M:00")
                alterou = True
                icon = "OK" if sucesso else "ERRO"
                print(f"[AGENDADOR] {icon} Notificacao {notif['id']} disparada para chat {notif['chat_id']}.")

        if alterou:
            _salvar_fila(fila)


def _loop_verificacao():
    while True:
        threading.Event().wait(INTERVALO_VERIFICACAO)
        _verificar_e_disparar()


def inicializar_agendador():
    """
    Inicializa o agendador. Deve ser chamado uma vez no boot do sistema.
    Executa boot recovery (dispara notificações vencidas) e inicia thread.
    """
    global _thread_iniciada
    if _thread_iniciada:
        return

    print("[AGENDADOR] Verificando notificacoes pendentes do boot...")
    _verificar_e_disparar()

    pendentes = contar_pendentes()
    if pendentes > 0:
        print(f"[AGENDADOR] {pendentes} notificacao(oes) aguardando disparo.")
    else:
        print("[AGENDADOR] Nenhuma notificacao pendente.")

    t = threading.Thread(target=_loop_verificacao, daemon=True)
    t.start()
    _thread_iniciada = True
    print(f"[AGENDADOR] Thread iniciada (verificacao a cada {INTERVALO_VERIFICACAO}s).")
