"""
TREMBINHO - Ponte Telegram ↔ Motor (Sprint 4 / Passo 5)
========================================================
Orquestrador que amarra as 3 peças do sistema:
    Listener (transporte) → Ponte (orquestração) → Motor (raciocínio)

RESPONSABILIDADES:
1. Receber texto cru vindo do listener.
2. Interceptar comandos especiais (/reset, /start, /help, /status).
3. Buscar histórico de conversa do chat (via memoria.py).
4. Chamar o motor com auto_confirmar=True (gravação sem [Y/n]).
5. Salvar histórico atualizado de volta na memória.
6. Disparar typing action durante o processamento (UX tipo WhatsApp).
7. Enviar resposta de volta via Telegram (com fila de retry).
8. Partir mensagens longas (>4096 chars).

Essa camada mantém o listener e o motor totalmente desacoplados.
"""

import os
import time
import threading
import requests
from dotenv import load_dotenv

from trembinho.agente import processar_mensagem
from trembinho.memoria import obter_historico, salvar_historico, resetar_historico, tamanho_historico
from trembinho.notificador import enviar_mensagem_telegram

# -----------------------------------------------------------------------------
# Credenciais e constantes
# -----------------------------------------------------------------------------
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Telegram corta mensagens >4096 chars. Usamos 4000 pra dar margem ao HTML parse.
LIMITE_CHARS_TELEGRAM = 4000

# Intervalo entre typing actions (dura 5s no Telegram, renovamos a cada 4s)
INTERVALO_TYPING = 4


# -----------------------------------------------------------------------------
# Typing indicator (roda em thread paralela enquanto o Ollama processa)
# -----------------------------------------------------------------------------
def _enviar_typing_action(chat_id):
    """Dispara um sendChatAction('typing') único. Dura ~5s no Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendChatAction"
    try:
        requests.post(url, json={"chat_id": chat_id, "action": "typing"}, timeout=5)
    except requests.exceptions.RequestException:
        pass  # Typing é cosmético, falha silenciosa.


def _manter_typing_ativo(chat_id, evento_parar):
    """
    Roda em thread separada. Renova o typing a cada 4s até o evento ser setado.
    Garante que o 'Trembinho está digitando...' não expire durante chamadas
    longas do Ollama (14B pode levar 10-15s pra responder).
    """
    while not evento_parar.is_set():
        _enviar_typing_action(chat_id)
        evento_parar.wait(INTERVALO_TYPING)


# -----------------------------------------------------------------------------
# Envio de resposta com suporte a mensagens longas
# -----------------------------------------------------------------------------
def _enviar_resposta(chat_id, texto):
    """
    Envia resposta ao usuário. Se passar do limite do Telegram, particiona.
    Reaproveita enviar_mensagem_telegram() do notificador.py (fila de retry grátis).
    """
    if not texto:
        texto = "(Trembinho ficou sem palavras. Tenta reformular?)"

    # Particiona se necessário, quebrando preferencialmente em \n
    if len(texto) <= LIMITE_CHARS_TELEGRAM:
        enviar_mensagem_telegram(texto)
        return

    pedacos = []
    restante = texto
    while len(restante) > LIMITE_CHARS_TELEGRAM:
        corte = restante.rfind("\n", 0, LIMITE_CHARS_TELEGRAM)
        if corte == -1:
            corte = LIMITE_CHARS_TELEGRAM
        pedacos.append(restante[:corte])
        restante = restante[corte:].lstrip("\n")
    if restante:
        pedacos.append(restante)

    for i, pedaco in enumerate(pedacos, 1):
        prefixo = f"[{i}/{len(pedacos)}] " if len(pedacos) > 1 else ""
        enviar_mensagem_telegram(prefixo + pedaco)


# -----------------------------------------------------------------------------
# Comandos especiais (interceptados antes do motor)
# -----------------------------------------------------------------------------
def _tratar_comando_especial(chat_id, texto):
    """
    Trata comandos começando com /. Retorna True se o comando foi tratado
    (e portanto o motor NÃO deve ser chamado). False se é mensagem normal.
    """
    comando = texto.strip().lower().split()[0] if texto.strip() else ""

    if comando == "/reset":
        resetar_historico(chat_id)
        _enviar_resposta(chat_id, "🧹 Histórico zerado. Podemos começar do zero, chefe.")
        return True

    if comando in ("/start", "/help"):
        _enviar_resposta(
            chat_id,
            "🚂 <b>Trembinho na área!</b>\n\n"
            "Manda em linguagem natural:\n"
            "• <i>'anota lead Matheus da XP pra amanhã às 14h'</i>\n"
            "• <i>'quais tarefas tenho essa semana?'</i>\n"
            "• <i>'o que tem pra hoje?'</i>\n\n"
            "Comandos:\n"
            "/reset - zera nossa conversa\n"
            "/status - mostra estado atual\n"
            "/help - mostra isso aqui"
        )
        return True

    if comando == "/status":
        qtd = tamanho_historico(chat_id)
        _enviar_resposta(
            chat_id,
            f"📊 <b>Status do Trembinho</b>\n\n"
            f"• Mensagens no histórico: {qtd}\n"
            f"• Motor: Qwen 2.5 14B (Ollama local)\n"
            f"• Canal: Telegram (bidirecional)"
        )
        return True

    return False


# -----------------------------------------------------------------------------
# Entry point: callback que o listener vai injetar
# -----------------------------------------------------------------------------
def processar_mensagem_telegram(chat_id, texto):
    """
    Callback principal chamado pelo telegram_listener a cada mensagem autorizada.
    
    Args:
        chat_id: ID do chat do Telegram (int ou str).
        texto: conteúdo da mensagem recebida.
    """
    # 1) Interceptação de comandos especiais
    if _tratar_comando_especial(chat_id, texto):
        return

    # 2) Dispara typing action em thread paralela
    evento_parar_typing = threading.Event()
    thread_typing = threading.Thread(
        target=_manter_typing_ativo,
        args=(chat_id, evento_parar_typing),
        daemon=True,
    )
    thread_typing.start()

    try:
        # 3) Busca histórico e chama o motor
        historico = obter_historico(chat_id)
        resposta, historico_atualizado = processar_mensagem(
            texto,
            historico,
            auto_confirmar_gravacao=True,  # Telegram não tem [Y/n] interativo
        )

        # 4) Salva histórico atualizado (com janela deslizante aplicada)
        salvar_historico(chat_id, historico_atualizado)

    finally:
        # 5) Para o typing independente do que rolou
        evento_parar_typing.set()

    # 6) Envia resposta de volta (com retry/fila do notificador)
    _enviar_resposta(chat_id, resposta)