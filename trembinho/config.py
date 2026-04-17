"""
Módulo de configurações do Trembinho.
Responsável por ler o .env e disponibilizar as chaves de API.
"""

import os
from pathlib import Path
from dotenv import load_dotenv


def carregar_configuracoes():
    """
    Lê o arquivo .env e carrega as chaves de API.
    Retorna um dicionário com as chaves encontradas.
    """
    
    # Sobe 1 nível (de trembinho/config.py para trembinho/) pra achar o .env
    pasta_raiz_projeto = Path(__file__).parent.parent.resolve()
    caminho_env = pasta_raiz_projeto / ".env"
    
    load_dotenv(dotenv_path=caminho_env)
    
    config = {
        "gemini_api_key": os.getenv("GEMINI_API_KEY"),
        "notion_api_key": os.getenv("NOTION_API_KEY"),
        "notion_database_id": os.getenv("NOTION_DATABASE_ID"),
        "google_credentials_path": os.getenv("GOOGLE_CREDENTIALS_PATH"),
    }
    
    return config


def validar_chave_gemini(config):
    """
    Verifica se a chave do Gemini está presente.
    Retorna True se OK, False se não.
    """
    
    if not config.get("gemini_api_key"):
        print("❌ ERRO: Chave GEMINI_API_KEY não encontrada no arquivo .env")
        return False
    
    return True