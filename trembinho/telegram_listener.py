"""
TREMBINHO - Listener Telegram (Long Polling)
=============================================
O "Ouvido" do Trembinho. Roda em loop perguntando ao Telegram se há
mensagens novas. Quando chega uma, valida o chat_id (firewall) e
repassa o texto para um callback injetado pelo orquestrador.

ARQUITETURA:
- Long Polling puro (requests + timeout=30). Sem webhooks, sem expor portas.
- Offset persistido em disco (telegram_offset.txt) - sobrevive a reinícios.
- Firewall de chat_id: rejeita sumariamente quem não é o dono.
- Backoff exponencial em falha de rede (5s -> 10s -> 20s -> 60s).
- Callback injetável: o motor do agente vem no Passo 5, sem acoplamento aqui.

USO (Passo 3 - standalone):
    python -m trembinho.telegram_listener
    
    Nesse modo, o callback default só imprime as mensagens no console.
    Útil pra validar que o ouvido está escutando antes de plugar o cérebro.
"""

import os
import json
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

# -----------------------------------------------------------------------------
# Credenciais e constantes
# -----------------------------------------------------------------------------
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

ARQUIVO_OFFSET = "telegram_offset.txt"
TIMEOUT_LONG_POLLING = 30  # segundos que o Telegram segura a conexão aberta
TIMEOUT_REQUEST = 40       # timeout do requests (maior que o long polling pra margem)

# Backoff exponencial em erro de rede
BACKOFF_INICIAL = 5
BACKOFF_MAXIMO = 60


# -----------------------------------------------------------------------------
# Persistência do offset (último update_id processado)
# -----------------------------------------------------------------------------
def _carregar_offset():
    """Lê o último update_id processado do disco. Retorna 0 se não existir."""
    if not os.path.exists(ARQUIVO_OFFSET):
        return 0
    try:
        with open(ARQUIVO_OFFSET, "r", encoding="utf-8") as f:
            return int(f.read().strip() or "0")
    except (ValueError, IOError) as e:
        print(f"⚠️  [OFFSET] Arquivo corrompido, começando do zero: {e}")
        return 0


def _salvar_offset(update_id):
    """Persiste o update_id mais recente processado."""
    try:
        with open(ARQUIVO_OFFSET, "w", encoding="utf-8") as f:
            f.write(str(update_id))
    except IOError as e:
        print(f"⚠️  [OFFSET] Falha ao salvar ({e}). Vai reprocessar na próxima reinicialização.")


# -----------------------------------------------------------------------------
# Firewall de chat_id
# -----------------------------------------------------------------------------
def _chat_id_autorizado(chat_id_recebido):
    """Compara o chat_id da mensagem recebida com o autorizado no .env."""
    if not TELEGRAM_CHAT_ID:
        return False
    return str(chat_id_recebido) == str(TELEGRAM_CHAT_ID).strip()


# -----------------------------------------------------------------------------
# Chamada ao endpoint getUpdates do Telegram
# -----------------------------------------------------------------------------
def _buscar_updates(offset):
    """
    Long Polling: pergunta ao Telegram se há mensagens novas desde o offset.
    Retorna lista de updates ou None em caso de erro de rede.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {
        "offset": offset,
        "timeout": TIMEOUT_LONG_POLLING,
        "allowed_updates": ["message"],  # só mensagens de texto, ignora edits/callbacks/etc
    }

    try:
        resposta = requests.get(url, params=params, timeout=TIMEOUT_REQUEST)
        if resposta.status_code != 200:
            print(f"❌ [TELEGRAM API] Status {resposta.status_code}: {resposta.text[:200]}")
            return None

        dados = resposta.json()
        if not dados.get("ok"):
            print(f"❌ [TELEGRAM API] Resposta não-ok: {dados}")
            return None

        return dados.get("result", [])

    except requests.exceptions.Timeout:
        # Timeout é esperado no long polling quando não há mensagem. Não é erro.
        return []
    except requests.exceptions.RequestException as e:
        print(f"📡 [REDE] Falha de conexão: {e}")
        return None


# -----------------------------------------------------------------------------
# Extração do texto e do chat_id de um update
# -----------------------------------------------------------------------------
def _extrair_info_update(update):
    """
    Extrai {update_id, chat_id, texto, nome_usuario} de um update do Telegram.
    Retorna None se o update não for uma mensagem de texto válida.
    """
    update_id = update.get("update_id")
    mensagem = update.get("message") or {}
    texto = mensagem.get("text")
    chat = mensagem.get("chat") or {}
    chat_id = chat.get("id")
    nome_usuario = (mensagem.get("from") or {}).get("first_name", "desconhecido")

    if not (update_id and texto and chat_id):
        return None

    return {
        "update_id": update_id,
        "chat_id": chat_id,
        "texto": texto,
        "nome_usuario": nome_usuario,
    }


# -----------------------------------------------------------------------------
# Callback default (modo standalone/teste do Passo 3)
# -----------------------------------------------------------------------------
def _callback_default(texto_recebido):
    """Callback usado quando o listener roda sozinho, sem o motor conectado."""
    agora = datetime.now().strftime("%H:%M:%S")
    print(f"\n📨 [{agora}] Mensagem recebida: {texto_recebido}")
    print("   (modo teste - motor do agente ainda não conectado)")


# -----------------------------------------------------------------------------
# Loop principal do listener
# -----------------------------------------------------------------------------
def rodar_listener(callback_processar_mensagem=None):
    """
    Loop infinito de Long Polling.
    
    Args:
        callback_processar_mensagem: função que recebe (texto: str) e retorna
            a resposta (str) a ser enviada de volta ao usuário.
            Se None, usa callback de teste que só imprime no console.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ [ERRO] TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID ausentes no .env.")
        return

    if callback_processar_mensagem is None:
        callback_processar_mensagem = _callback_default

    print("=" * 60)
    print("👂 TREMBINHO LISTENER - Long Polling ativo")
    print(f"   Chat autorizado: {TELEGRAM_CHAT_ID}")
    print(f"   Timeout polling: {TIMEOUT_LONG_POLLING}s")
    print("   Pressione Ctrl+C para encerrar.")
    print("=" * 60)

    offset = _carregar_offset()
    if offset > 0:
        # +1 porque o Telegram retorna updates >= offset, e a gente quer o PRÓXIMO
        offset += 1
        print(f"📂 [OFFSET] Retomando a partir de update_id={offset}")

    backoff_atual = BACKOFF_INICIAL

    try:
        while True:
            updates = _buscar_updates(offset)

            # Erro de rede: backoff exponencial
            if updates is None:
                print(f"⏸️  [BACKOFF] Aguardando {backoff_atual}s antes de tentar de novo...")
                time.sleep(backoff_atual)
                backoff_atual = min(backoff_atual * 2, BACKOFF_MAXIMO)
                continue

            # Sucesso: reseta o backoff
            backoff_atual = BACKOFF_INICIAL

            # Lista vazia = timeout do long polling sem mensagens. Normal.
            if not updates:
                continue

            for update in updates:
                info = _extrair_info_update(update)
                if not info:
                    # Update sem texto (sticker, foto, etc) - avança offset e ignora
                    offset = update.get("update_id", offset) + 1
                    _salvar_offset(offset - 1)
                    continue

                # -------------------------------------------------------------
                # FIREWALL: rejeita qualquer chat_id não autorizado
                # -------------------------------------------------------------
                if not _chat_id_autorizado(info["chat_id"]):
                    print(
                        f"🚫 [FIREWALL] Mensagem rejeitada | "
                        f"chat_id={info['chat_id']} | "
                        f"nome={info['nome_usuario']} | "
                        f"texto={info['texto'][:50]!r}"
                    )
                    offset = info["update_id"] + 1
                    _salvar_offset(info["update_id"])
                    continue

                # -------------------------------------------------------------
                # Chat autorizado: aciona o callback
                # -------------------------------------------------------------
                agora = datetime.now().strftime("%H:%M:%S")
                print(f"\n✅ [{agora}] De: {info['nome_usuario']} ({info['chat_id']})")
                print(f"   Texto: {info['texto']}")

                try:
                    callback_processar_mensagem(info["texto"])
                except Exception as e:
                    print(f"❌ [CALLBACK] Erro ao processar mensagem: {e}")

                # Avança o offset somente depois de processar
                offset = info["update_id"] + 1
                _salvar_offset(info["update_id"])

    except KeyboardInterrupt:
        print("\n\n" + "=" * 60)
        print("👋 Listener encerrado pelo usuário (Ctrl+C). Até a próxima!")
        print("=" * 60)


# -----------------------------------------------------------------------------
# Execução standalone (modo teste do Passo 3)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    rodar_listener()