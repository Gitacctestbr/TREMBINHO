"""
TREMBINHO - Módulo Notificador (Telegram)
====================================================
Responsável por disparar mensagens ativas para o SDR.
Inclui sistema de 'Fila de Retry' para falhas de rede.
"""

import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

# Carrega as credenciais
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Caminho do arquivo de fila (salvo na raiz do projeto)
ARQUIVO_FILA = "fila_retry_telegram.txt"


def salvar_na_fila(mensagem):
    """Salva a mensagem num txt local se a internet cair (Dívida Técnica prevenida)."""
    try:
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(ARQUIVO_FILA, "a", encoding="utf-8") as f:
            linha = json.dumps({"data": agora, "mensagem": mensagem})
            f.write(linha + "\n")
        print(f"⏳ [RETRY] Mensagem salva na fila local ({ARQUIVO_FILA}).")
    except Exception as e:
        print(f"❌ [ERRO GRAVE] Falha ao salvar na fila de retry: {e}")


def processar_fila_retry():
    """Lê o arquivo de fila e tenta reenviar as mensagens pendentes."""
    if not os.path.exists(ARQUIVO_FILA):
        return

    print("🔄 [RETRY] Processando mensagens represadas...")
    mensagens_pendentes = []
    
    with open(ARQUIVO_FILA, "r", encoding="utf-8") as f:
        linhas = f.readlines()

    sucessos = 0
    for linha in linhas:
        try:
            dados = json.loads(linha.strip())
            # Tenta reenviar (silenciosamente)
            if enviar_mensagem_telegram(dados["mensagem"], silencioso=True):
                sucessos += 1
            else:
                mensagens_pendentes.append(linha) # Falhou de novo, mantém na fila
        except Exception:
            continue

    # Reescreve o arquivo só com o que continuou falhando
    if mensagens_pendentes:
        with open(ARQUIVO_FILA, "w", encoding="utf-8") as f:
            f.writelines(mensagens_pendentes)
    else:
        os.remove(ARQUIVO_FILA) # Limpou tudo
        
    if sucessos > 0:
        print(f"✅ [RETRY] {sucessos} mensagens antigas foram entregues com sucesso!")


def enviar_mensagem_telegram(mensagem, silencioso=False):
    """
    Dispara um POST para a API do Telegram.
    Se falhar, joga para a fila de retry (a menos que já seja um retry).
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        if not silencioso:
            print("❌ [ERRO] Chaves do Telegram ausentes no .env.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Formatando para HTML pra ficar bonito no chat (negrito, itálico)
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "HTML"
    }

    try:
        # Timeout curto (10s) pra não travar o bot se a internet estiver instável
        resposta = requests.post(url, json=payload, timeout=10)
        
        if resposta.status_code == 200:
            if not silencioso:
                print("✅ [TELEGRAM] Mensagem entregue no seu celular!")
            return True
        else:
            if not silencioso:
                print(f"❌ [TELEGRAM ERRO] A API recusou: {resposta.text}")
                salvar_na_fila(mensagem)
            return False
            
    except requests.exceptions.RequestException as e:
        if not silencioso:
            print(f"📡 [REDE] Sem internet ou timeout. Jogando pra fila...")
            salvar_na_fila(mensagem)
        return False