"""
TREMBINHO - Segundo Cérebro SDR
Arquivo de entrada: main.py
"""

import os
import threading
from dotenv import load_dotenv
from trembinho.telegram_listener import rodar_listener
from trembinho.ponte_telegram import processar_mensagem_telegram
from trembinho.agente import processar_mensagem
from trembinho.memoria import obter_historico, salvar_historico
from trembinho.agendador import inicializar_agendador


def _validar_env():
    """Verifica se as variáveis obrigatórias estão no .env."""
    obrigatorias = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "NOTION_API_KEY", "NOTION_DATABASE_ID"]
    faltando = [k for k in obrigatorias if not os.getenv(k)]
    if faltando:
        print(f"❌ ERRO: Variáveis ausentes no .env: {', '.join(faltando)}")
        return False
    return True


def _callback(texto):
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    processar_mensagem_telegram(chat_id, texto)


def main():
    load_dotenv()

    print("=" * 50)
    print("🧠 TREMBINHO - Segundo Cérebro SDR")
    print("=" * 50)

    if not _validar_env():
        return

    print("✅ Configurações validadas.")
    inicializar_agendador()
    print("🚀 Iniciando bot Telegram em background...")
    print("=" * 50)

    # Inicia listener em thread separada (daemon = não bloqueia saída do programa)
    thread_listener = threading.Thread(
        target=rodar_listener,
        kwargs={"callback_processar_mensagem": _callback},
        daemon=True
    )
    thread_listener.start()

    # Terminal ativo no thread principal
    print("\n💬 Terminal ativo. Você pode digitar mensagens aqui ou enviar via Telegram.")
    print("   Digite 'sair' para encerrar.\n")
    print("=" * 50)

    chat_id_local = os.getenv("TELEGRAM_CHAT_ID")
    try:
        while True:
            texto = input("Você: ").strip()
            if texto.lower() == "sair":
                break
            if texto:
                historico = obter_historico(chat_id_local)
                resposta, historico_atualizado = processar_mensagem(
                    texto, historico, auto_confirmar_gravacao=True
                )
                salvar_historico(chat_id_local, historico_atualizado)
                print(f"\nTrembinho: {resposta}\n")
    except KeyboardInterrupt:
        pass
    finally:
        print("\n" + "=" * 50)
        print("Encerrando o Trembinho. Boa sorte nas vendas!")
        print("=" * 50)


if __name__ == "__main__":
    main()
