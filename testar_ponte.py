"""Teste manual do Passo 5 - Listener + Ponte + Motor integrados."""
from trembinho.telegram_listener import rodar_listener
from trembinho.ponte_telegram import processar_mensagem_telegram

def callback(texto):
    # O listener atual passa só o texto. Vamos usar o TELEGRAM_CHAT_ID do .env
    # como chat_id por enquanto (no Passo 6 a gente refina).
    import os
    from dotenv import load_dotenv
    load_dotenv()
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    processar_mensagem_telegram(chat_id, texto)

if __name__ == "__main__":
    rodar_listener(callback_processar_mensagem=callback)