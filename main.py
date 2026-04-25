"""
TREMBINHO - Segundo Cérebro SDR
Arquivo de entrada: main.py
"""

import os
import sys
import threading
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from trembinho.telegram_listener import rodar_listener
from trembinho.ponte_telegram import processar_mensagem_telegram
from trembinho.agente import processar_mensagem
from trembinho.memoria import obter_historico, salvar_historico, resetar_historico
from trembinho.agendador import inicializar_agendador
from trembinho.notificador import enviar_mensagem_telegram


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
    
    # -------------------------------------------------------------------------
    # BLINDAGEM DE CUSTO NÍVEL 2 (TELEGRAM): Intercepta comando de limpeza
    # -------------------------------------------------------------------------
    comando = texto.strip().lower()
    if comando in ["limpar", "/limpar", "reset", "/reset"]:
        resetar_historico(chat_id)
        enviar_mensagem_telegram("🧹 <b>Memória resetada!</b>\nContexto limpo. Pode mandar o próximo briefing ou lead.", silencioso=True)
        return

    processar_mensagem_telegram(chat_id, texto)


def main():
    load_dotenv()

    print("=" * 50)
    print("🧠 TREMBINHO - Segundo Cérebro SDR")
    print("=" * 50)

    if not _validar_env():
        return

    chat_id_local = os.getenv("TELEGRAM_CHAT_ID")

    # -------------------------------------------------------------------------
    # BLINDAGEM DE CUSTO NÍVEL 3 (BOOT): Garante que a sessão começa zerada
    # (A memória já é RAM, mas isso previne vazamentos se plugar SQLite depois)
    # -------------------------------------------------------------------------
    resetar_historico(chat_id_local)

    print("✅ Configurações validadas.")
    print("🧹 Memória de contexto zerada para a sessão de hoje.")
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
    print("   Digite 'limpar' para zerar o contexto e 'sair' para encerrar.\n")
    print("=" * 50)

    try:
        while True:
            texto = input("Você: ").strip()
            comando_terminal = texto.lower()

            if comando_terminal == "sair":
                break
                
            # -------------------------------------------------------------------------
            # BLINDAGEM DE CUSTO NÍVEL 2 (TERMINAL): Limpeza manual
            # -------------------------------------------------------------------------
            if comando_terminal in ["limpar", "/limpar", "reset", "/reset"]:
                resetar_historico(chat_id_local)
                print("\n🧠 Trembinho: Memória resetada com sucesso! Campo limpo.\n")
                continue

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