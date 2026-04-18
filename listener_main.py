"""
TREMBINHO - Entry Point Oficial do Bot (Passo 6)
================================================
Substitui testar_ponte.py. Este é o arquivo de produção.

Melhorias sobre testar_ponte.py:
- Loop de auto-reinício: se o listener cair por qualquer exceção,
  aguarda 15s e reinicia automaticamente.
- Log estruturado com timestamp (console + arquivo trembinho_bot.log).
- Validação de variáveis de ambiente na inicialização.
- Trava de segurança: para após 10 crashes consecutivos para evitar loop infinito.
- Ctrl+C encerra limpo, sem reiniciar.
"""

import os
import sys
import time
import logging
from dotenv import load_dotenv

from trembinho.telegram_listener import rodar_listener
from trembinho.ponte_telegram import processar_mensagem_telegram

# ---------------------------------------------------------------------------
# Logging: console + arquivo
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("trembinho_bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("trembinho")

# ---------------------------------------------------------------------------
# Constantes do loop de reinício
# ---------------------------------------------------------------------------
DELAY_REINICIO = 15       # segundos de espera antes de reiniciar após crash
MAX_CRASHES_CONSECUTIVOS = 10  # para o bot se crashar muitas vezes seguidas
JANELA_ESTABILIDADE = 300  # se rodar >5min sem crash, reseta o contador


# ---------------------------------------------------------------------------
# Validação de ambiente
# ---------------------------------------------------------------------------
def _validar_env():
    """Garante que as variáveis obrigatórias estão no .env. Aborta se faltar."""
    load_dotenv()
    obrigatorias = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "NOTION_API_KEY",
        "NOTION_DATABASE_ID",
    ]
    faltando = [v for v in obrigatorias if not os.getenv(v)]
    if faltando:
        log.error(f"Variáveis ausentes no .env: {', '.join(faltando)}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Callback injetado no listener
# ---------------------------------------------------------------------------
def _callback(texto):
    """Repassa texto + chat_id autorizado à ponte Telegram."""
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    processar_mensagem_telegram(chat_id, texto)


# ---------------------------------------------------------------------------
# Loop principal com auto-reinício
# ---------------------------------------------------------------------------
def main():
    _validar_env()

    log.info("=" * 55)
    log.info("🚂 TREMBINHO BOT — iniciando (produção / Passo 6)")
    log.info("=" * 55)

    crashes = 0

    while True:
        inicio = time.time()
        try:
            rodar_listener(callback_processar_mensagem=_callback)
            # rodar_listener só retorna normalmente após Ctrl+C (trata internamente)
            log.info("Listener encerrado normalmente. Saindo.")
            break

        except KeyboardInterrupt:
            log.info("Encerrado pelo usuário (Ctrl+C). Saindo.")
            break

        except Exception as e:
            duracao = time.time() - inicio

            # Se rodou estável por mais de 5min, reseta o contador de crashes
            if duracao > JANELA_ESTABILIDADE:
                crashes = 0

            crashes += 1
            log.error(f"[CRASH #{crashes}] {type(e).__name__}: {e}", exc_info=True)

            if crashes >= MAX_CRASHES_CONSECUTIVOS:
                log.critical(
                    f"Atingiu {MAX_CRASHES_CONSECUTIVOS} crashes consecutivos. "
                    "Abortando para evitar loop infinito. Verifique trembinho_bot.log."
                )
                sys.exit(2)

            log.info(f"Reiniciando em {DELAY_REINICIO}s... ({crashes}/{MAX_CRASHES_CONSECUTIVOS})")
            time.sleep(DELAY_REINICIO)


if __name__ == "__main__":
    main()
