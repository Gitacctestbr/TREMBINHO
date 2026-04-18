"""
TREMBINHO - Agendador de Notificações
======================================
Gerencia notificações agendadas em linguagem natural.

Responsabilidades:
- Persistir fila em JSON (notificacoes_agendadas.json) para boot recovery.
- Thread daemon de verificação a cada 30s.
- Limite configurável de notificações simultâneas (padrão: 3).
- Parsing de tempo em minutos/horas/dias (complementa o datas.py).
- Envio via Telegram com parse_mode HTML.
"""

import json
import os
import re
import threading
import uuid
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

ARQUIVO_FILA = "notificacoes_agendadas.json"
LIMITE_SIMULTANEAS = 3
INTERVALO_VERIFICACAO = 30  # segundos

_lock = threading.Lock()
_thread_iniciada = False


# -----------------------------------------------------------------------------
# Parsing de tempo relativo (minutos/horas não cobertos pelo datas.py)
# -----------------------------------------------------------------------------

# Padrões: "em 5 minutos", "daqui 10 min", "em 2h", "em 1h30", "daqui a 2 horas"
# ATENÇÃO: "em\s+" (com espaço) é obrigatório pra não comer "nome" e similares.
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


def interpretar_tempo_relativo(texto):
    """
    Converte expressão de tempo relativo em datetime absoluto.

    Aceita: "em 5 minutos", "daqui 2 horas", "em 1h30", "daqui a 10min",
            "em 30 segundos", "em 1h30min".

    Returns:
        datetime absoluto ou None se não conseguiu interpretar.
    """
    agora = datetime.now()

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

    # Fallback: tentar via datas.py (cobre "às 14h", "amanhã", dias da semana etc.)
    try:
        from trembinho.datas import interpretar_data
        resultado = interpretar_data(texto)
        if resultado:
            fmt = "%Y-%m-%dT%H:%M:00" if "T" in resultado else "%Y-%m-%d"
            return datetime.strptime(resultado, fmt)
    except Exception:
        pass

    return None


def formatar_disparo_humano(dt):
    """
    Converte datetime de disparo em texto legível.
    Ex: "em 5 min", "em 2h30", "às 14:30 de 19/04"
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

    # Mais de 24h: mostra data e hora
    return f"às {dt.strftime('%H:%M')} de {dt.strftime('%d/%m')}"


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
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": mensagem, "parse_mode": "HTML"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


# -----------------------------------------------------------------------------
# Geração de mensagem personalizada
# -----------------------------------------------------------------------------

def _gerar_mensagem_notificacao(contexto_original):
    """
    Pede ao Qwen para gerar um lembrete personalizado baseado no contexto original.
    Retorna string HTML pronta pra enviar no Telegram.
    """
    try:
        import ollama
        prompt = (
            "Você é o Trembinho, assistente SDR. "
            "Gere um lembrete curto e direto em HTML para Telegram (máx 3 linhas). "
            "Use <b> para destacar a ação principal. "
            "Comece com '⏰ <b>Lembrete!</b>\\n\\n'. "
            "Contexto do que o usuário pediu pra lembrar: "
            f'"{contexto_original}"\n\n'
            "Abaixo do lembrete gerado, adicione:\n"
            "<i>📝 Pedido original: " + contexto_original + "</i>\n\n"
            "Responda APENAS com o HTML da mensagem, sem explicações."
        )
        resp = ollama.chat(
            model="qwen2.5:14b",
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.4, "num_ctx": 1024},
        )
        return resp.message.content.strip()
    except Exception:
        # Fallback sem Qwen
        return (
            f"⏰ <b>Lembrete!</b>\n\n"
            f"{contexto_original}\n\n"
            f"<i>📝 Pedido original: {contexto_original}</i>"
        )


# -----------------------------------------------------------------------------
# API pública do módulo
# -----------------------------------------------------------------------------

def agendar_notificacao(chat_id, contexto_original, disparo_em_iso):
    """
    Adiciona uma notificação à fila e persiste no JSON.

    Args:
        chat_id: ID do chat Telegram (str ou int).
        contexto_original: texto exato que o usuário mandou.
        disparo_em_iso: datetime ISO ('2026-04-18T14:35:00') do disparo.

    Returns:
        (True, notif_dict)  — agendado com sucesso.
        (False, str_erro)   — falhou (limite atingido ou erro).
    """
    with _lock:
        fila = _carregar_fila()
        pendentes = sum(1 for n in fila if n.get("status") == "pendente")

        if pendentes >= LIMITE_SIMULTANEAS:
            return (False, f"Já tem {pendentes} notificações na fila. Limite é {LIMITE_SIMULTANEAS}.")

        mensagem_gerada = _gerar_mensagem_notificacao(contexto_original)

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
        print(f"[AGENDADOR] ✅ Notificação {notif['id']} agendada para {disparo_em_iso}.")
        return (True, notif)


def listar_pendentes():
    """Retorna lista das notificações com status 'pendente'."""
    fila = _carregar_fila()
    return [n for n in fila if n.get("status") == "pendente"]


def contar_pendentes():
    return len(listar_pendentes())


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
                icon = "✅" if sucesso else "❌"
                print(f"[AGENDADOR] {icon} Notificação {notif['id']} disparada para chat {notif['chat_id']}.")

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

    print("[AGENDADOR] Verificando notificações pendentes do boot...")
    _verificar_e_disparar()

    pendentes = contar_pendentes()
    if pendentes > 0:
        print(f"[AGENDADOR] {pendentes} notificação(ões) aguardando disparo.")
    else:
        print("[AGENDADOR] Nenhuma notificação pendente.")

    t = threading.Thread(target=_loop_verificacao, daemon=True)
    t.start()
    _thread_iniciada = True
    print(f"[AGENDADOR] Thread iniciada (verificação a cada {INTERVALO_VERIFICACAO}s).")
